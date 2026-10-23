from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, is_staff
from app.models.usage import UsageRecord
from app.models.user import UserRole
from app.schemas.usage import UsageRecordResponse
from app.services import reporting_service
from app.services.deployment_service import get_deployment_for_user

router = APIRouter()


@router.get("/summary")
async def usage_summary(
    days: int = Query(30, ge=1, le=90),
    scope: Literal["customer", "provider", "network"] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Inference requests and runtime-reported tokens per day and per deployment. Customers see their own
    deployments, providers see requests served by their nodes, and staff may ask for the whole network."""
    default = {UserRole.customer: "customer", UserRole.provider: "provider"}.get(current_user.role, "network")
    chosen = scope or default
    allowed = {"customer", "provider", "network"} if is_staff(current_user) else {default}
    if chosen not in allowed:
        raise HTTPException(status_code=403, detail=f"Scope '{chosen}' is not available to this account")
    return await reporting_service.usage_summary(db, current_user, days, chosen)


@router.get("/{deployment_id}", response_model=list[UsageRecordResponse])
async def get_usage(
    deployment_id: str,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    deployment = await get_deployment_for_user(db, deployment_id, current_user)
    result = await db.execute(
        select(UsageRecord)
        .filter(UsageRecord.deployment_id == deployment.id)
        .order_by(UsageRecord.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
