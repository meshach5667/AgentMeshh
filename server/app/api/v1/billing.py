"""Pricing (public) and rated charges (customers see what they paid, providers what they earned)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, is_staff
from app.core.timeutil import utcnow
from app.models.billing import Charge, PricingRule
from app.schemas.billing import ChargeOut, PricingOut, PricingRuleOut
from app.services import billing_service, ledger_service

router = APIRouter()


@router.get("/pricing", response_model=PricingOut)
async def pricing(db: AsyncSession = Depends(get_db)):
    """The price list in force (null when none is set: usage is then measured but not charged)."""
    upcoming = (
        (
            await db.execute(
                select(PricingRule).where(PricingRule.effective_from > utcnow()).order_by(PricingRule.effective_from)
            )
        )
        .scalars()
        .all()
    )
    current = await billing_service.active_rule(db)
    return PricingOut(
        current=PricingRuleOut.model_validate(current) if current else None,
        upcoming=[PricingRuleOut.model_validate(r) for r in upcoming],
        currency=settings.BILLING_CURRENCY,
        min_prepaid_hours=settings.BILLING_MIN_PREPAID_HOURS,
        billing_interval_seconds=settings.BILLING_INTERVAL_SECONDS,
    )


@router.get("/charges", response_model=list[ChargeOut])
async def charges(
    deployment_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Charges against the caller's wallet (as customer) or credited to it (as provider). Staff see all."""
    query = select(Charge).order_by(Charge.created_at.desc()).limit(limit)
    if not is_staff(current_user):
        wallet = await ledger_service.wallet_for_user(db, current_user.id)
        query = query.where(or_(Charge.customer_wallet_id == wallet.id, Charge.provider_wallet_id == wallet.id))
    if deployment_id:
        query = query.where(Charge.deployment_id == deployment_id)
    rows = (await db.execute(query)).scalars().all()
    await db.commit()
    return rows
