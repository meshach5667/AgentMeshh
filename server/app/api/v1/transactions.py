from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.schemas.transaction import TransactionResponse

router = APIRouter()


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    result = await db.execute(select(Wallet).filter(Wallet.user_id == current_user.id))
    wallet = result.scalars().first()
    if not wallet:
        return []
    result = await db.execute(
        select(Transaction)
        .filter(or_(Transaction.from_wallet == wallet.id, Transaction.to_wallet == wallet.id))
        .order_by(Transaction.created_at.desc())
    )
    return result.scalars().all()
