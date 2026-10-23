from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.deployment import Deployment
from app.models.node import Node
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import Provider
from app.models.wallet import Wallet
from app.schemas.earnings import EarningsSummary
from app.schemas.transaction import TransactionResponse
from app.services.deployment_lifecycle import ACTIVE

router = APIRouter()


async def _hosted_deployments(db: AsyncSession, user_id) -> tuple[int, int]:
    """Deployments ever placed on, and currently active on, the caller's nodes."""
    owned = select(Node.id).join(Provider, Node.owner_id == Provider.id).where(Provider.user_id == user_id)
    on_nodes = Deployment.node_id.in_(owned)
    total = (await db.execute(select(func.count(Deployment.id)).where(on_nodes))).scalar() or 0
    active = (
        await db.execute(
            select(func.count(Deployment.id)).where(on_nodes, Deployment.status.in_([s.value for s in ACTIVE]))
        )
    ).scalar() or 0
    return int(total), int(active)


@router.get("", response_model=EarningsSummary)
async def get_earnings(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    total_deployments, active_deployments = await _hosted_deployments(db, current_user.id)
    result = await db.execute(select(Wallet).filter(Wallet.user_id == current_user.id))
    wallet = result.scalars().first()
    if not wallet:
        return EarningsSummary(
            total_earnings=Decimal(0),
            pending_earnings=Decimal(0),
            available_balance=Decimal(0),
            total_deployments=total_deployments,
            active_deployments=active_deployments,
        )

    settled = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.to_wallet == wallet.id,
            Transaction.type == TransactionType.PROVIDER_CREDIT,
            Transaction.status == TransactionStatus.SETTLED,
        )
    )
    total_earnings = settled.scalar() or 0

    pending = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.to_wallet == wallet.id,
            Transaction.type == TransactionType.PROVIDER_CREDIT,
            Transaction.status == TransactionStatus.PENDING,
        )
    )
    pending_earnings = pending.scalar() or 0

    return EarningsSummary(
        total_earnings=Decimal(total_earnings),
        pending_earnings=Decimal(pending_earnings),
        available_balance=Decimal(wallet.balance or 0),
        total_deployments=total_deployments,
        active_deployments=active_deployments,
    )


@router.get("/history", response_model=list[TransactionResponse])
async def get_history(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    result = await db.execute(select(Wallet).filter(Wallet.user_id == current_user.id))
    wallet = result.scalars().first()
    if not wallet:
        return []
    result = await db.execute(
        select(Transaction)
        .filter(Transaction.to_wallet == wallet.id, Transaction.type == TransactionType.PROVIDER_CREDIT)
        .order_by(Transaction.created_at.desc())
    )
    return result.scalars().all()
