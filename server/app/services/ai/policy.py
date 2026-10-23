"""Deterministic policy for autonomous deployments.

Everything the model proposes is checked here against the catalog, the customer's autonomy limits, platform
ceilings, current prices, and the customer's wallet. None of these checks depend on the model's output being
truthful: the model only chooses among options the application then verifies.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.model import Model, ModelArtifact
from app.services import billing_service, ledger_service
from app.services.catalog_service import (
    MAX_NUM_CTX,
    RUNTIME_PREFERENCE,
    DeploymentConfig,
    ResourceRequest,
    deployable_artifacts,
    estimate_requirements,
)
from app.services.ledger_service import money

Runtime = Literal["ollama", "llamacpp", "vllm"]
Source = Literal["ollama", "huggingface"]


class AutonomyLimits(BaseModel):
    """What the customer authorizes the agent to do without asking again. Enforced in code, never by prompt."""

    model_config = ConfigDict(extra="forbid")

    max_spend: Decimal = Field(gt=0, le=Decimal("100000000"), description="Most this deployment may cost in total")
    max_duration_hours: float = Field(gt=0, description="The deployment is stopped after this long")
    max_cpu_cores: int = Field(4, ge=1, le=256)
    max_ram_mb: int = Field(16384, ge=512, le=2_097_152)
    max_vram_mb: int = Field(0, ge=0, le=1_048_576, description="0 means no GPU")
    max_recovery_attempts: int = Field(1, ge=0)
    allowed_runtimes: list[Runtime] = Field(default_factory=lambda: ["ollama", "llamacpp", "vllm"], min_length=1)  # type: ignore[arg-type]
    allowed_sources: list[Source] = Field(default_factory=lambda: ["ollama", "huggingface"], min_length=1)  # type: ignore[arg-type]

    @field_validator("max_duration_hours")
    @classmethod
    def _duration_cap(cls, v: float) -> float:
        if v > settings.AI_MAX_DEPLOYMENT_HOURS:
            raise ValueError(f"must be at most {settings.AI_MAX_DEPLOYMENT_HOURS} hours")
        return v

    @field_validator("max_recovery_attempts")
    @classmethod
    def _recovery_cap(cls, v: int) -> int:
        if v > settings.AI_MAX_RECOVERY_ATTEMPTS:
            raise ValueError(f"must be at most {settings.AI_MAX_RECOVERY_ATTEMPTS}")
        return v

    @field_validator("allowed_runtimes", "allowed_sources")
    @classmethod
    def _dedupe(cls, v: list) -> list:
        return list(dict.fromkeys(v))


class DeploymentPlan(BaseModel):
    """A deployment the model proposes. Only these fields exist; the application fills in everything else."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_id: uuid.UUID
    runtime: Runtime | None = None
    num_ctx: int = Field(2048, ge=512, le=MAX_NUM_CTX)
    require_gpu: bool = False
    region: str | None = Field(None, max_length=100, pattern=r"^[A-Za-z0-9 ._-]*$")
    duration_hours: float = Field(gt=0, le=24 * 365)


@dataclass
class Candidate:
    artifact: ModelArtifact
    req: ResourceRequest


@dataclass
class PlanCheck:
    ok: bool
    violations: list[str] = field(default_factory=list)
    model: Model | None = None
    candidates: list[Candidate] = field(default_factory=list)
    currency: str = settings.BILLING_CURRENCY
    priced: bool = False
    hourly: Decimal = Decimal(0)
    total: Decimal = Decimal(0)

    def summary(self) -> dict:
        return {
            "valid": self.ok,
            "violations": self.violations[:10],
            "runtimes": [c.artifact.runtime for c in self.candidates],
            "requirements": [c.req.__dict__ for c in self.candidates][:3],
            "cost": {
                "priced": self.priced,
                "currency": self.currency,
                "hourly": str(self.hourly),
                "total": str(self.total),
            },
        }


def resource_violations(req: ResourceRequest, limits: AutonomyLimits) -> list[str]:
    out = []
    if req.cpu_cores > limits.max_cpu_cores:
        out.append(f"{req.runtime}: needs {req.cpu_cores} CPU cores, limit is {limits.max_cpu_cores}")
    if req.ram_mb > limits.max_ram_mb:
        out.append(f"{req.runtime}: needs {req.ram_mb} MB RAM, limit is {limits.max_ram_mb}")
    if req.gpu_required and limits.max_vram_mb <= 0:
        out.append(f"{req.runtime}: needs a GPU, but GPU use is not authorized")
    elif req.vram_mb > limits.max_vram_mb:
        out.append(f"{req.runtime}: needs {req.vram_mb} MB VRAM, limit is {limits.max_vram_mb}")
    return out


async def hourly_cost(db: AsyncSession, req: ResourceRequest) -> tuple[bool, str, Decimal]:
    """(priced, currency, hourly price) for a reservation at the pricing version in force now."""
    rule = await billing_service.active_rule(db)
    if billing_service.is_free(rule):
        return False, settings.BILLING_CURRENCY, Decimal(0)
    assert rule is not None
    return (
        True,
        rule.currency,
        money(billing_service.hourly_resource_price(rule, req.cpu_cores, req.ram_mb, req.vram_mb)),
    )


async def check_plan(
    db: AsyncSession, plan: DeploymentPlan, limits: AutonomyLimits, user_id: uuid.UUID, *, check_balance: bool = True
) -> PlanCheck:
    """Validate a proposed plan. Candidates are the runtimes that satisfy every limit, in preference order."""
    check = PlanCheck(ok=False)
    try:
        model = await _approved_model(db, plan.model_id)
        artifacts = await deployable_artifacts(db, model, plan.runtime)
    except HTTPException as exc:
        check.violations.append(str(exc.detail) if isinstance(exc.detail, str) else "model is not deployable")
        return check
    check.model = model
    if plan.duration_hours > limits.max_duration_hours:
        check.violations.append(
            f"duration {plan.duration_hours:g} h exceeds the authorized {limits.max_duration_hours:g} h"
        )
    config = DeploymentConfig(num_ctx=plan.num_ctx, region=plan.region, require_gpu=plan.require_gpu)
    for artifact in artifacts:
        if artifact.runtime not in limits.allowed_runtimes:
            check.violations.append(f"{artifact.runtime}: runtime not authorized")
            continue
        if artifact.source_type not in limits.allowed_sources:
            check.violations.append(f"{artifact.runtime}: model source '{artifact.source_type}' not authorized")
            continue
        req = estimate_requirements(artifact, config)
        problems = resource_violations(req, limits)
        if problems:
            check.violations.extend(problems)
            continue
        check.candidates.append(Candidate(artifact, req))
    if not check.candidates:
        if not check.violations:
            check.violations.append("no runtime of this model is allowed by the limits")
        return check

    # Price the most expensive candidate so the estimate holds whichever runtime gets a node.
    hours = Decimal(str(plan.duration_hours))
    for c in check.candidates:
        priced, currency, hourly = await hourly_cost(db, c.req)
        check.priced, check.currency = priced or check.priced, currency
        check.hourly = max(check.hourly, hourly)
    check.total = money(check.hourly * hours)
    if check.total > limits.max_spend:
        check.violations.append(
            f"estimated cost {check.total} {check.currency} for {plan.duration_hours:g} h exceeds the "
            f"authorized maximum of {money(limits.max_spend)}"
        )
    if check_balance and check.priced:
        wallet = await ledger_service.wallet_for_user(db, user_id)
        have = await ledger_service.balance(db, wallet.id)
        if have < check.total:
            check.violations.append(
                f"wallet balance {money(have)} {check.currency} does not cover the estimated {check.total}"
            )
    # Violations about other runtimes do not block a plan that still has a valid runtime; cost and duration do.
    blocking = [v for v in check.violations if v.split(":", 1)[0] not in RUNTIME_PREFERENCE]
    check.ok = not blocking
    return check


async def _approved_model(db: AsyncSession, model_id: uuid.UUID) -> Model:
    model = await db.get(Model, model_id)
    if model is None or not model.is_approved:
        raise HTTPException(status_code=404, detail="model is not in the approved catalog")
    return model
