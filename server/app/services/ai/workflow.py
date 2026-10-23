"""Persistent workflow for AI deployment runs.

    PLANNING -> SUBMITTING -> DEPLOYING -> VERIFYING -> READY
    DEPLOYING | VERIFYING | READY -> RECOVERING -> DEPLOYING        (bounded by max_recovery_attempts)
    VERIFYING | READY -> DEPLOYING                                  (the platform moved it to another node)
    DEPLOYING | VERIFYING | READY | RECOVERING -> STOPPING -> COMPLETED | CANCELLED | FAILED
    any non-terminal -> FAILED;  PLANNING | SUBMITTING | RECOVERING -> CANCELLED

The model is consulted only in PLANNING and RECOVERING, through queued inference requests. Every other step
is deterministic: submission, verification, limit enforcement, and stopping keep working while the inference
machine is offline, and a run waiting for the model simply stays where it is until the request is answered or
expires (then it fails without inventing a decision).

``advance`` is safe to call at any time from any replica: a lease on the run serializes processing, and
each step is idempotent (submission uses an idempotency key derived from the run).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import session_scope
from app.core.db_utils import rowcount
from app.core.logging import redact
from app.core.timeutil import utcnow
from app.models.ai import AiInferenceRequest, AiRun, AiRunEvent
from app.models.billing import Charge
from app.models.deployment import Deployment
from app.models.deployment import DeploymentStatus as DepStatus
from app.models.model import Model, ModelArtifact
from app.models.user import Customer, User
from app.services import audit_service, deployment_lifecycle
from app.services.ai import agent, inference_queue, tools
from app.services.ai.policy import AutonomyLimits, DeploymentPlan, check_plan
from app.services.catalog_service import artifact_problem
from app.services.ledger_service import money

logger = logging.getLogger(__name__)


class R(StrEnum):
    PLANNING = "PLANNING"
    SUBMITTING = "SUBMITTING"
    DEPLOYING = "DEPLOYING"
    VERIFYING = "VERIFYING"
    READY = "READY"
    RECOVERING = "RECOVERING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset({R.COMPLETED, R.FAILED, R.CANCELLED})
TRANSITIONS: dict[R, frozenset[R]] = {
    R.PLANNING: frozenset({R.SUBMITTING, R.FAILED, R.CANCELLED}),
    R.SUBMITTING: frozenset({R.DEPLOYING, R.FAILED, R.CANCELLED}),
    R.DEPLOYING: frozenset({R.VERIFYING, R.RECOVERING, R.STOPPING, R.COMPLETED, R.FAILED}),
    R.VERIFYING: frozenset({R.READY, R.DEPLOYING, R.RECOVERING, R.STOPPING, R.COMPLETED, R.FAILED}),
    R.READY: frozenset({R.DEPLOYING, R.RECOVERING, R.STOPPING, R.COMPLETED, R.FAILED}),
    R.RECOVERING: frozenset({R.DEPLOYING, R.STOPPING, R.FAILED, R.CANCELLED}),
    R.STOPPING: frozenset({R.COMPLETED, R.CANCELLED, R.FAILED}),
    R.COMPLETED: frozenset(),
    R.FAILED: frozenset(),
    R.CANCELLED: frozenset(),
}
MAX_PROBE_FAILURES = 3
LEASE_SECONDS = 300  # longer than one probe or one submission
STOP_RESULT = {"cancelled": R.CANCELLED, "verification_failed": R.FAILED}


class InvalidRunTransition(Exception):  # noqa: N818
    pass


# --- Small helpers -------------------------------------------------------------------------------------


def event(db: AsyncSession, run: AiRun, kind: str, message: str, data: dict | None = None) -> None:
    db.add(
        AiRunEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            kind=kind,
            message=redact(message)[:2000],
            data=data,
            created_at=utcnow(),
        )
    )


def transition(
    db: AsyncSession, run: AiRun, new: R, message: str, *, error_code: str | None = None, **fields: Any
) -> None:
    current = R(run.status)
    if new == current:
        return
    if new not in TRANSITIONS[current]:
        raise InvalidRunTransition(f"{current} -> {new} is not allowed")
    now = utcnow()
    run.status = new.value
    run.updated_at = now
    for key, value in fields.items():
        setattr(run, key, value)
    if error_code:
        run.error_code = error_code
        run.error_message = redact(message)[:2000]
    if new in TERMINAL:
        run.completed_at = now
        run.pending_request_id = None
        run.conversation = None
    db.add(
        AiRunEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            kind="state",
            from_status=current.value,
            to_status=new.value,
            message=redact(message)[:2000],
            created_at=now,
        )
    )


def limits_of(run: AiRun) -> AutonomyLimits:
    return AutonomyLimits.model_validate(run.limits)


async def actual_cost(db: AsyncSession, run: AiRun) -> Decimal:
    ids = [uuid.UUID(str(d)) for d in (run.deployment_ids or [])]
    if not ids:
        return Decimal(0)
    total = (
        await db.execute(select(func.coalesce(func.sum(Charge.amount), 0)).where(Charge.deployment_id.in_(ids)))
    ).scalar()
    return money(total or 0)


async def projected_cost(db: AsyncSession, run: AiRun, dep: Deployment | None) -> Decimal:
    """Rated charges plus READY time not rated yet, at the estimated hourly price."""
    cost = await actual_cost(db, run)
    if dep is not None and dep.status == DepStatus.READY.value and run.estimated_hourly:
        since = dep.metered_until or dep.ready_at or dep.created_at
        if dep.metered_until and dep.ready_at and dep.ready_at > dep.metered_until:
            since = dep.ready_at
        hours = Decimal(str(max(0.0, (utcnow() - since).total_seconds()))) / Decimal(3600)
        cost += money(Decimal(run.estimated_hourly) * hours)
    return cost


async def catalog_for(db: AsyncSession, limits: AutonomyLimits) -> list[dict]:
    """Approved models with at least one valid artifact the limits allow. Trusted data for the prompt."""
    models = (await db.execute(select(Model).where(Model.is_approved.is_(True)))).scalars().all()
    out = []
    for m in models:
        artifacts: list[ModelArtifact] = [
            a
            for a in (m.artifacts or [])
            if a.is_enabled
            and artifact_problem(a) is None
            and a.runtime in limits.allowed_runtimes
            and a.source_type in limits.allowed_sources
            and (limits.max_vram_mb > 0 or not a.gpu_required)
        ]
        if not artifacts:
            continue
        out.append(
            {
                "id": str(m.id),
                "name": tools.clip(m.name, 80),
                "family": tools.clip(m.family, 40),
                "publisher": tools.clip(m.publisher, 40),
                "parameter_size": tools.clip(m.parameter_size, 20),
                "runtimes": sorted({a.runtime for a in artifacts}),
                "min_ram_mb": min(a.min_ram_mb for a in artifacts),
                "gpu_required": all(a.gpu_required for a in artifacts),
            }
        )
    return out


@dataclass
class Ctx:
    db: AsyncSession
    run: AiRun
    user: User
    customer: Customer

    def tool_ctx(self) -> tools.ToolContext:
        return tools.ToolContext(self.db, self.run, self.user, self.customer)

    async def tool(self, name: str, args: dict) -> tools.ToolResult:
        result = await tools.execute(self.tool_ctx(), name, args, caller="system")
        # A refused submission rolls the session back; reload the run so later steps see durable state.
        for obj in (self.run, self.user, self.customer):
            await self.db.refresh(obj)
        status = "ok" if result.ok else f"error: {result.data.get('error')}"
        event(self.db, self.run, "tool", f"{name}: {status}", {"tool": name, "result": _brief(result.data)})
        return result


def _brief(data: dict) -> dict:
    return {k: (tools.clip(v, 200) if isinstance(v, str) else v) for k, v in list(data.items())[:10]}


# --- Model conversations -------------------------------------------------------------------------------


async def _ask(ctx: Ctx, phase: str) -> bool:
    """Queue the next model turn for the current conversation. Returns False if the queue is full (the run
    waits and tries again on the next pass)."""
    run = ctx.run
    try:
        req = await inference_queue.enqueue(
            ctx.db,
            run_id=run.id,
            purpose=phase,
            messages=agent.bounded(run.conversation or []),
            schema=agent.output_schema(phase),
        )
    except inference_queue.QueueFull:
        return False
    run.pending_request_id = req.id
    health = await inference_queue.health(ctx.db)
    if health.available:
        event(ctx.db, run, "ai", "Waiting for the AI service", {"request_id": str(req.id)})
    else:
        event(
            ctx.db,
            run,
            "info",
            f"{health.message} This step expires if it is not answered within "
            f"{settings.AI_QUEUE_TTL_SECONDS // 60} minutes.",
            {"request_id": str(req.id), "ai_status": health.status},
        )
    return True


async def _next_reply(ctx: Ctx, phase: str) -> agent.ParsedReply | None:
    """Drive the conversation until the model produces a final answer. Returns it, or None when the run is
    waiting for the model or has failed."""
    run = ctx.run
    if run.phase != phase or run.conversation is None:
        return None  # caller starts the conversation
    if run.pending_request_id is None:
        if run.agent_steps >= settings.AI_MAX_AGENT_STEPS:
            transition(
                ctx.db,
                run,
                R.FAILED,
                "The AI agent reached its step limit without a decision",
                error_code="AGENT_STEP_LIMIT",
            )
            return None
        await _ask(ctx, phase)
        return None
    req = await ctx.db.get(AiInferenceRequest, run.pending_request_id)
    if req is None or req.status in ("PENDING", "LEASED"):
        return None
    run.pending_request_id = None
    if req.status != "COMPLETED":
        reason = {
            "EXPIRED": "The AI service was unavailable and the request expired",
            "CANCELLED": "The AI request was cancelled",
        }.get(req.status, f"The AI service failed to answer ({req.error_code})")
        transition(
            ctx.db,
            run,
            R.FAILED,
            f"{reason}. No AI decision was made, so nothing further was done.",
            error_code="AI_UNAVAILABLE" if req.status == "EXPIRED" else "AI_ERROR",
        )
        return None

    run.agent_steps += 1
    content = str((req.result or {}).get("content") or "")
    run.conversation = [*(run.conversation or []), {"role": "assistant", "content": content[: agent.MAX_MESSAGE_CHARS]}]
    try:
        reply = agent.parse_reply(content, phase)
    except agent.InvalidReply as exc:
        event(ctx.db, run, "error", f"The AI reply was invalid: {exc}")
        run.conversation = [*run.conversation, agent.correction_message(str(exc))]
        return None  # the next pass asks again (step limit applies)

    if reply.explanation:
        run.explanation = reply.explanation
    if reply.action != "call_tool":
        return reply

    if run.tool_calls >= settings.AI_MAX_TOOL_CALLS:
        transition(ctx.db, run, R.FAILED, "The AI agent reached its tool-call limit", error_code="TOOL_CALL_LIMIT")
        return None
    run.tool_calls += 1
    result = await tools.execute(ctx.tool_ctx(), reply.tool or "", reply.arguments, caller="agent", phase=phase)
    event(
        ctx.db,
        run,
        "tool",
        f"AI requested {tools.clip(reply.tool, 60)}: {'ok' if result.ok else result.data.get('error')}",
        {"tool": tools.clip(reply.tool, 60), "arguments": _brief(reply.arguments or {}), "ok": result.ok},
    )
    run.conversation = [*run.conversation, agent.tool_result_message(reply.tool or "", result.as_dict())]
    return None


# --- Steps ---------------------------------------------------------------------------------------------


async def _plan(ctx: Ctx) -> None:
    run = ctx.run
    if run.cancel_requested:
        await inference_queue.cancel(ctx.db, run.pending_request_id)
        transition(ctx.db, run, R.CANCELLED, "Cancelled before a deployment was created")
        return
    limits = limits_of(run)
    if run.phase != tools.PLANNING or run.conversation is None:
        catalog = await catalog_for(ctx.db, limits)
        if not catalog:
            transition(
                ctx.db, run, R.FAILED, "No approved model can be deployed within these limits", error_code="NO_MODEL"
            )
            return
        lines = agent.catalog_lines(catalog, run.request_text)
        run.phase = tools.PLANNING
        run.conversation = agent.planning_messages(run, limits, lines, settings.BILLING_CURRENCY)
        run.agent_steps = 0
        await _ask(ctx, tools.PLANNING)
        return
    reply = await _next_reply(ctx, tools.PLANNING)
    if reply is None or reply.plan is None:
        return
    check = await check_plan(ctx.db, reply.plan, limits, ctx.user.id)
    event(
        ctx.db,
        run,
        "ai",
        "AI proposed a plan" + ("" if check.ok else " that AgentMesh rejected"),
        {"plan": reply.plan.model_dump(mode="json"), "check": check.summary()},
    )
    if not check.ok:
        problem = "the plan violates policy: " + "; ".join(check.violations)
        run.conversation = [*(run.conversation or []), agent.correction_message(problem)]
        return
    transition(
        ctx.db,
        run,
        R.SUBMITTING,
        f"Plan accepted: {check.model.name if check.model else 'model'} for {reply.plan.duration_hours:g} h",
        plan=reply.plan.model_dump(mode="json"),
        currency=check.currency,
        estimated_hourly=check.hourly,
        estimated_total=check.total,
        conversation=None,
        phase=None,
    )


async def _stray_deployments(ctx: Ctx) -> list[Deployment]:
    """Deployments created for this run that it never recorded (a crash right after submission)."""
    return list(
        (
            await ctx.db.execute(
                select(Deployment).where(
                    Deployment.customer_id == ctx.customer.id,
                    Deployment.idempotency_key.like(f"ai:{ctx.run.id}:%"),
                )
            )
        )
        .scalars()
        .all()
    )


async def _submit(ctx: Ctx) -> None:
    run = ctx.run
    if run.cancel_requested:
        for dep in await _stray_deployments(ctx):
            if DepStatus(dep.status) not in deployment_lifecycle.TERMINAL:
                run.deployment_ids = sorted({*(run.deployment_ids or []), str(dep.id)})
                await ctx.tool("rollback_deployment", {"deployment_id": str(dep.id)})
        transition(ctx.db, run, R.CANCELLED, "Cancelled before the deployment started")
        return
    await ctx.db.commit()  # the plan is durable before anything is created
    result = await ctx.tool("submit_deployment", {"plan": run.plan})
    if not result.ok:
        transition(
            ctx.db,
            run,
            R.FAILED,
            f"The deployment could not be created: {result.data.get('message')}",
            error_code=str(result.data.get("error") or "SUBMIT_FAILED")[:100].upper(),
        )
        return
    _adopt(ctx, result.data)
    hours = DeploymentPlan.model_validate(run.plan).duration_hours
    transition(
        ctx.db,
        run,
        R.DEPLOYING,
        "Deployment submitted; capacity reserved on a provider node",
        deadline_at=run.deadline_at or utcnow() + timedelta(hours=hours),
    )


def _adopt(ctx: Ctx, data: dict) -> None:
    run = ctx.run
    run.deployment_id = uuid.UUID(data["deployment_id"])
    run.deployment_ids = [*(run.deployment_ids or []), data["deployment_id"]]
    run.endpoint = None
    run.probe_failures = 0
    if data.get("estimated_hourly") is not None:
        run.estimated_hourly = Decimal(data["estimated_hourly"])
        run.currency = data.get("currency") or run.currency


async def _enforce_limits(ctx: Ctx, dep: Deployment | None) -> bool:
    """Cancellation, maximum duration, and maximum spend. Returns True if the run is now stopping."""
    run = ctx.run
    limits = limits_of(run)
    reason = None
    if run.cancel_requested:
        reason, message = "cancelled", "Cancellation requested"
    elif run.deadline_at and utcnow() >= run.deadline_at:
        reason, message = "max_duration", f"Reached the authorized duration of {limits.max_duration_hours:g} h"
    elif await projected_cost(ctx.db, run, dep) >= Decimal(limits.max_spend):
        reason, message = "max_spend", f"Reached the authorized spend of {money(limits.max_spend)} {run.currency or ''}"
    if reason is None:
        return False
    if dep is not None and DepStatus(dep.status) not in deployment_lifecycle.TERMINAL:
        await ctx.tool("rollback_deployment", {"deployment_id": str(dep.id)})
    await inference_queue.cancel(ctx.db, run.pending_request_id)
    transition(ctx.db, run, R.STOPPING, message, stop_reason=reason, pending_request_id=None, endpoint=None)
    return True


async def _current_deployment(ctx: Ctx) -> Deployment | None:
    return await ctx.db.get(Deployment, ctx.run.deployment_id) if ctx.run.deployment_id else None


async def _watch(ctx: Ctx) -> None:
    """DEPLOYING, VERIFYING, READY: follow the deployment the platform is running."""
    run = ctx.run
    dep = await _current_deployment(ctx)
    if dep is not None:
        await ctx.db.refresh(dep)
    if await _enforce_limits(ctx, dep):
        return
    if dep is None:
        transition(ctx.db, run, R.FAILED, "The deployment record is missing", error_code="DEPLOYMENT_MISSING")
        return
    status = DepStatus(dep.status)
    if status == DepStatus.FAILED:
        transition(ctx.db, run, R.RECOVERING, f"The deployment failed: {dep.error_code or 'error'}", endpoint=None)
        return
    if status in (DepStatus.STOPPED, DepStatus.CANCELLED) or dep.deleted_at is not None:
        transition(ctx.db, run, R.COMPLETED, "The deployment was stopped outside the agent", endpoint=None)
        return
    current = R(run.status)
    if status == DepStatus.READY and current == R.DEPLOYING:
        transition(ctx.db, run, R.VERIFYING, "The provider reports the model is serving; verifying it")
        current = R.VERIFYING
    if current == R.VERIFYING:
        if status != DepStatus.READY:
            transition(ctx.db, run, R.DEPLOYING, f"The deployment is {status.value}; waiting")
            return
        await ctx.db.commit()  # keep the lease and state durable during the network check
        result = await ctx.tool("run_health_check", {"deployment_id": str(dep.id)})
        if result.ok and result.data.get("healthy"):
            transition(
                ctx.db, run, R.READY, "Verified with a real test completion; endpoint published", endpoint=dep.endpoint
            )
            return
        run.probe_failures += 1
        if run.probe_failures >= MAX_PROBE_FAILURES:
            await ctx.tool("rollback_deployment", {"deployment_id": str(dep.id)})
            transition(
                ctx.db,
                run,
                R.STOPPING,
                f"The deployment failed verification {run.probe_failures} times: {result.data.get('detail')}",
                stop_reason="verification_failed",
            )
        return
    if current == R.READY and status not in (DepStatus.READY, DepStatus.UNHEALTHY):
        # The platform moved it to another node; verify again once it is back.
        transition(ctx.db, run, R.DEPLOYING, f"The deployment is being moved ({status.value})", endpoint=None)


async def _recover(ctx: Ctx) -> None:
    run = ctx.run
    limits = limits_of(run)
    dep = await _current_deployment(ctx)
    if run.cancel_requested:
        await inference_queue.cancel(ctx.db, run.pending_request_id)
        if dep is not None and DepStatus(dep.status) not in deployment_lifecycle.TERMINAL:
            await ctx.tool("rollback_deployment", {"deployment_id": str(dep.id)})
            transition(ctx.db, run, R.STOPPING, "Cancellation requested", stop_reason="cancelled")
        else:
            transition(ctx.db, run, R.CANCELLED, "Cancelled during recovery")
        return
    if await _enforce_limits(ctx, dep):
        return
    if run.recovery_attempts >= limits.max_recovery_attempts:
        detail = f"{dep.error_code}: {tools.clip(dep.error_message, 200)}" if dep else "unknown error"
        transition(
            ctx.db,
            run,
            R.FAILED,
            f"The deployment failed ({detail}) and the authorized recovery attempts "
            f"({limits.max_recovery_attempts}) are used up",
            error_code="RECOVERY_LIMIT",
        )
        return
    if run.phase != tools.RECOVERY or run.conversation is None:
        failure = {
            "deployment_id": str(dep.id) if dep else None,
            "status": dep.status if dep else None,
            "error_code": dep.error_code if dep else None,
            "error_message": tools.clip(dep.error_message, 300) if dep else None,
            "runtime": dep.runtime if dep else None,
            "schedule_attempts": dep.schedule_attempts if dep else None,
        }
        run.phase = tools.RECOVERY
        run.conversation = agent.recovery_messages(run, failure, limits.max_recovery_attempts - run.recovery_attempts)
        run.agent_steps = 0
        await _ask(ctx, tools.RECOVERY)
        return
    reply = await _next_reply(ctx, tools.RECOVERY)
    if reply is None or reply.recovery_action is None:
        return
    event(ctx.db, run, "ai", f"AI recommended: {reply.recovery_action}", {"recovery_action": reply.recovery_action})
    if reply.recovery_action == "abandon":
        transition(
            ctx.db,
            run,
            R.FAILED,
            f"The AI agent recommended giving up: {run.explanation or ''}",
            error_code="ABANDONED",
        )
        return
    if dep is None:
        transition(ctx.db, run, R.FAILED, "Nothing to recover", error_code="DEPLOYMENT_MISSING")
        return
    if reply.recovery_action == "restart" and dep.status not in (DepStatus.READY.value, DepStatus.UNHEALTHY.value):
        run.conversation = [
            *(run.conversation or []),
            agent.correction_message(f"restart is not possible: the deployment is {dep.status}"),
        ]
        return
    run.recovery_attempts += 1
    run.conversation, run.phase = None, None
    await ctx.db.commit()  # count the attempt before acting, so a crash cannot repeat it for free
    dep_id = str(dep.id)
    result = await ctx.tool("request_recovery_action", {"deployment_id": dep_id, "action": reply.recovery_action})
    if not result.ok:
        transition(
            ctx.db,
            run,
            R.FAILED,
            f"Recovery ({reply.recovery_action}) was refused: {result.data.get('message')}",
            error_code="RECOVERY_FAILED",
        )
        return
    if result.data.get("deployment_id") and result.data["deployment_id"] != dep_id:
        _adopt(ctx, result.data)
    transition(
        ctx.db, run, R.DEPLOYING, f"Recovery attempt {run.recovery_attempts}: {reply.recovery_action}", endpoint=None
    )


async def _stopping(ctx: Ctx) -> None:
    run = ctx.run
    dep = await _current_deployment(ctx)
    if dep is not None:
        await ctx.db.refresh(dep)
        if DepStatus(dep.status) not in deployment_lifecycle.TERMINAL:
            return
    final = STOP_RESULT.get(run.stop_reason or "", R.COMPLETED)
    message = {
        R.CANCELLED: "Cancelled; the deployment is stopped",
        R.FAILED: "Stopped after failing verification",
    }.get(final, "Stopped after reaching an authorized limit")
    transition(ctx.db, run, final, message, error_code="VERIFICATION_FAILED" if final == R.FAILED else None)


STEPS = {
    R.PLANNING: _plan,
    R.SUBMITTING: _submit,
    R.DEPLOYING: _watch,
    R.VERIFYING: _watch,
    R.READY: _watch,
    R.RECOVERING: _recover,
    R.STOPPING: _stopping,
}


# --- Driver --------------------------------------------------------------------------------------------


async def _claim(db: AsyncSession, run_id: uuid.UUID, owner: str) -> bool:
    now = utcnow()
    result = await db.execute(
        update(AiRun)
        .where(AiRun.id == run_id, or_(AiRun.lease_until.is_(None), AiRun.lease_until < now))
        .values(lease_owner=owner, lease_until=now + timedelta(seconds=LEASE_SECONDS))
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return rowcount(result) == 1


async def advance(run_id: uuid.UUID, max_steps: int = 6) -> str | None:
    """Move a run forward as far as it can go without waiting. Returns its status, or None if another
    process holds it."""
    owner = uuid.uuid4().hex
    async with session_scope() as db:
        if not await _claim(db, run_id, owner):
            return None
        try:
            run = await db.get(AiRun, run_id)
            if run is None:
                return None
            await db.refresh(run)
            user = await db.get(User, run.user_id)
            customer = await db.get(Customer, run.customer_id)
            assert user is not None and customer is not None
            ctx = Ctx(db, run, user, customer)
            for _ in range(max_steps):
                status = R(run.status)
                if status in TERMINAL:
                    break
                before = (run.status, run.pending_request_id, run.agent_steps)
                await STEPS[status](ctx)
                await db.commit()
                if (run.status, run.pending_request_id, run.agent_steps) == before:
                    break
            return str(run.status)
        except Exception:
            await db.rollback()
            logger.exception("AI run %s failed to advance", run_id)
            raise
        finally:
            await db.execute(
                update(AiRun)
                .where(AiRun.id == run_id, AiRun.lease_owner == owner)
                .values(lease_owner=None, lease_until=None)
                .execution_options(synchronize_session=False)
            )
            await db.commit()


async def run_due(limit: int = 100) -> int:
    """Background pass: expire inference requests, then advance every unfinished run once."""
    async with session_scope() as db:
        await inference_queue.expire(db)
        await db.commit()
        ids = (
            (
                await db.execute(
                    select(AiRun.id)
                    .where(AiRun.status.not_in([s.value for s in TERMINAL]))
                    .order_by(AiRun.updated_at)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    for run_id in ids:
        try:
            await advance(run_id)
        except Exception:  # noqa: BLE001
            pass  # logged in advance; other runs still progress
    return len(ids)


# --- Customer operations -------------------------------------------------------------------------------


async def get_customer(db: AsyncSession, user: User) -> Customer:
    customer = (await db.execute(select(Customer).where(Customer.user_id == user.id))).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=403, detail="Customer account required")
    return customer


async def get_run_for_user(db: AsyncSession, run_id: str, user: User) -> AiRun:
    from app.core.dependencies import is_staff
    from app.core.ids import parse_uuid

    run = await db.get(AiRun, parse_uuid(run_id, "AI deployment"))
    if run is not None and not is_staff(user):
        customer = (await db.execute(select(Customer).where(Customer.user_id == user.id))).scalar_one_or_none()
        if customer is None or run.customer_id != customer.id:
            run = None
    if run is None:
        raise HTTPException(status_code=404, detail="AI deployment not found")
    await db.refresh(run)
    return run


async def create_run(
    db: AsyncSession, user: User, request_text: str, limits: AutonomyLimits, idempotency_key: str | None
) -> AiRun:
    customer = await get_customer(db, user)
    if idempotency_key:
        existing = (
            await db.execute(
                select(AiRun).where(AiRun.customer_id == customer.id, AiRun.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    health = await inference_queue.health(db)
    if health.status == "not_configured":
        raise HTTPException(
            status_code=503,
            detail={"code": "ai_not_configured", "message": "The AI deployment agent is not configured."},
        )
    if health.queue_depth >= settings.AI_QUEUE_MAX_LENGTH:
        raise HTTPException(
            status_code=503,
            detail={"code": "ai_queue_full", "message": "The AI service is busy. Try again in a few minutes."},
        )
    now = utcnow()
    run = AiRun(
        id=uuid.uuid4(),
        customer_id=customer.id,
        user_id=user.id,
        status=R.PLANNING.value,
        idempotency_key=idempotency_key,
        request_text=request_text,
        limits=limits.model_dump(mode="json"),
        deployment_ids=[],
        currency=settings.BILLING_CURRENCY,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    try:
        await db.flush()
    except Exception:
        await db.rollback()
        if idempotency_key:
            existing = (
                await db.execute(
                    select(AiRun).where(AiRun.customer_id == customer.id, AiRun.idempotency_key == idempotency_key)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
        raise
    db.add(
        AiRunEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            kind="state",
            to_status=R.PLANNING.value,
            message="Request received",
            created_at=now,
        )
    )
    audit_service.record(
        db,
        actor_id=user.id,
        action="ai_deployment.requested",
        resource_type="ai_run",
        resource_id=run.id,
        details={"limits": {k: str(v) for k, v in run.limits.items()}},
    )
    await db.commit()
    return run


async def request_cancel(db: AsyncSession, run: AiRun, user: User) -> None:
    if R(run.status) in TERMINAL:
        raise HTTPException(status_code=409, detail=f"AI deployment is already {run.status}")
    await db.execute(
        update(AiRun)
        .where(AiRun.id == run.id)
        .values(cancel_requested=True)
        .execution_options(synchronize_session=False)
    )
    audit_service.record(
        db, actor_id=user.id, action="ai_deployment.cancel_requested", resource_type="ai_run", resource_id=run.id
    )
    await db.commit()


async def view(db: AsyncSession, run: AiRun) -> dict:
    dep = await db.get(Deployment, run.deployment_id) if run.deployment_id else None
    if dep is not None:
        await db.refresh(dep)
    model_name = None
    if run.plan:
        model = await db.get(Model, uuid.UUID(str(run.plan["model_id"])))
        model_name = model.name if model else None
    waiting = False
    if run.pending_request_id:
        req = await db.get(AiInferenceRequest, run.pending_request_id)
        waiting = req is not None and req.status in inference_queue.OPEN
    endpoint = run.endpoint if run.status == R.READY.value else None
    return {
        "id": run.id,
        "status": run.status,
        "request": run.request_text,
        "limits": run.limits,
        "plan": run.plan,
        "model_name": model_name,
        "deployment_id": run.deployment_id,
        "deployment_ids": run.deployment_ids or [],
        "deployment_status": dep.status if dep else None,
        "runtime": dep.runtime if dep else None,
        "endpoint": endpoint,
        "openai_base_url": endpoint.rsplit("/", 1)[0] + "/v1" if endpoint else None,
        "explanation": run.explanation,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "currency": run.currency,
        "estimated_hourly": run.estimated_hourly,
        "estimated_total": run.estimated_total,
        "actual_cost": await actual_cost(db, run),
        "recovery_attempts": run.recovery_attempts,
        "agent_steps": run.agent_steps,
        "tool_calls": run.tool_calls,
        "waiting_for_ai": waiting,
        "cancel_requested": run.cancel_requested,
        "stop_reason": run.stop_reason,
        "deadline_at": run.deadline_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "completed_at": run.completed_at,
    }
