"""Operator endpoints. Every route requires the operator or admin role."""

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_roles
from app.models.model import Model
from app.models.transaction import Transaction
from app.models.user import UserRole
from app.schemas.billing import PayoutDecision, PayoutOut, PricingRuleCreate, PricingRuleOut
from app.schemas.deployment import DeploymentOut
from app.schemas.model import ModelOut
from app.schemas.node import NodeOut
from app.schemas.transaction import TransactionResponse
from app.services import audit_service, billing_service, payments_service, reconciliation_service, reporting_service

logger = logging.getLogger(__name__)
router = APIRouter()
staff_only = require_roles(UserRole.operator, UserRole.admin)


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str | None
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime | None


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def audit_logs(
    action: str | None = Query(None, max_length=100),
    resource_type: str | None = Query(None, max_length=100),
    resource_id: str | None = Query(None, max_length=100),
    actor_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _staff=Depends(staff_only),
):
    return await audit_service.search(
        db, action=action, resource_type=resource_type, resource_id=resource_id, actor_id=actor_id, limit=limit
    )


class AdminNodeOut(NodeOut):
    owner_email: str | None = None


class AdminDeploymentOut(DeploymentOut):
    customer_email: str | None = None


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _staff=Depends(staff_only)):
    """Network-wide counts: nodes and deployments by status, catalog, last-24h usage, and ledger totals."""
    return await reporting_service.operator_overview(db)


@router.get("/nodes", response_model=list[AdminNodeOut])
async def all_nodes(
    status: str | None = Query(None, max_length=20),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _staff=Depends(staff_only),
):
    rows = await reporting_service.list_nodes_with_owner(db, status, limit)
    return [AdminNodeOut(**NodeOut.model_validate(n).model_dump(), owner_email=email) for n, email in rows]


@router.get("/deployments", response_model=list[AdminDeploymentOut])
async def all_deployments(
    status: str | None = Query(None, max_length=20),
    node_id: uuid.UUID | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _staff=Depends(staff_only),
):
    rows = await reporting_service.list_deployments_with_owner(db, status, node_id, limit)
    return [
        AdminDeploymentOut(**DeploymentOut.model_validate(d).model_dump(exclude={"openai_base_url"}), customer_email=e)
        for d, e in rows
    ]


@router.get("/models", response_model=list[ModelOut])
async def all_models(db: AsyncSession = Depends(get_db), _staff=Depends(staff_only)):
    """The whole catalog, including unapproved models and disabled artifacts."""
    return (await db.execute(select(Model).order_by(Model.name))).scalars().all()


@router.get("/transactions", response_model=list[TransactionResponse])
async def ledger(
    limit: int = Query(200, ge=1, le=1000), db: AsyncSession = Depends(get_db), _staff=Depends(staff_only)
):
    return (await db.execute(select(Transaction).order_by(Transaction.created_at.desc()).limit(limit))).scalars().all()


@router.get("/pricing", response_model=list[PricingRuleOut])
async def pricing_versions(db: AsyncSession = Depends(get_db), _staff=Depends(staff_only)):
    return await billing_service.list_rules(db)


@router.post("/pricing", response_model=PricingRuleOut, status_code=201)
async def create_pricing_version(req: PricingRuleCreate, db: AsyncSession = Depends(get_db), staff=Depends(staff_only)):
    """Publish a new, immutable pricing version. It applies from ``effective_from`` (now or later); usage
    before that keeps the price it was rated at."""
    return await billing_service.create_rule(db, req.model_dump(), staff)


@router.get("/payouts", response_model=list[PayoutOut])
async def payouts(
    status: str | None = Query(None, max_length=20), db: AsyncSession = Depends(get_db), _staff=Depends(staff_only)
):
    return await payments_service.list_payouts(db, None, status)


@router.post("/payouts/{payout_id}/approve", response_model=PayoutOut)
async def approve_payout(payout_id: uuid.UUID, db: AsyncSession = Depends(get_db), staff=Depends(staff_only)):
    return await payments_service.decide_payout(db, str(payout_id), staff, True, None)


@router.post("/payouts/{payout_id}/reject", response_model=PayoutOut)
async def reject_payout(
    payout_id: uuid.UUID, req: PayoutDecision, db: AsyncSession = Depends(get_db), staff=Depends(staff_only)
):
    return await payments_service.decide_payout(db, str(payout_id), staff, False, req.reason)


@router.get("/reconciliation")
async def reconciliation_report(db: AsyncSession = Depends(get_db), _staff=Depends(staff_only)):
    """Ledger invariants and open payment items. Read-only."""
    return await reconciliation_service.report(db)


@router.post("/reconciliation/run")
async def reconciliation_run(staff=Depends(staff_only)):
    """Ask Paystack about stale top-ups and payouts and apply the answers (also runs in the background)."""
    result = await reconciliation_service.run()
    logger.info("Reconciliation run by %s: %s", staff.id, result)
    return result
