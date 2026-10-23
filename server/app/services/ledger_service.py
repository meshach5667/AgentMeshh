"""The ledger: the only code that changes wallet balances.

Rules (checked by reconciliation_service):

* A debit (``from_wallet``) applies while the entry is PENDING or SETTLED; a credit (``to_wallet``) applies
  only when SETTLED. So: balance = settled credits - (pending + settled) debits.
* Balances change with ``UPDATE ... SET balance = balance + :delta`` in the caller's transaction, never by
  read-modify-write, so concurrent postings cannot lose updates.
* Every posting carries an idempotency key (unique in the database). Posting the same key twice returns the
  existing entry and changes nothing.
* All amounts are in settings.BILLING_CURRENCY; a wallet in another currency is refused.

Nothing here commits.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db_utils import rowcount
from app.core.timeutil import utcnow
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.wallet import Wallet

QUANTUM = Decimal("0.00000001")
DEBIT_STATES = (TransactionStatus.PENDING.value, TransactionStatus.SETTLED.value)


def money(value: Decimal | int | str | float) -> Decimal:
    return Decimal(str(value)).quantize(QUANTUM, rounding=ROUND_HALF_UP)


async def wallet_for_user(db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> Wallet:
    """The user's wallet, created in the billing currency if missing. Does not commit."""
    query = select(Wallet).where(Wallet.user_id == user_id)
    if lock:
        query = query.with_for_update()
    wallet = (await db.execute(query)).scalars().first()
    if wallet is None:
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, balance=Decimal(0), currency=settings.BILLING_CURRENCY)
        db.add(wallet)
        await db.flush()
    return wallet


def _check_currency(wallet: Wallet | None) -> None:
    if wallet is not None and (wallet.currency or settings.BILLING_CURRENCY) != settings.BILLING_CURRENCY:
        raise HTTPException(
            status_code=409,
            detail=f"Wallet currency {wallet.currency} differs from the billing currency {settings.BILLING_CURRENCY}",
        )


async def _adjust(db: AsyncSession, wallet_id: uuid.UUID, delta: Decimal) -> None:
    await db.execute(
        update(Wallet)
        .where(Wallet.id == wallet_id)
        .values(balance=Wallet.balance + delta)
        .execution_options(synchronize_session=False)
    )


async def _existing(db: AsyncSession, key: str) -> Transaction | None:
    return (await db.execute(select(Transaction).where(Transaction.idempotency_key == key))).scalars().first()


async def post(
    db: AsyncSession,
    *,
    key: str,
    type: TransactionType,
    amount: Decimal,
    status: TransactionStatus = TransactionStatus.SETTLED,
    from_wallet: Wallet | None = None,
    to_wallet: Wallet | None = None,
    reference: str | None = None,
    description: str | None = None,
    deployment_id: uuid.UUID | None = None,
) -> Transaction:
    """Record one ledger entry and apply its balance effects. Idempotent on ``key``."""
    existing = await _existing(db, key)
    if existing is not None:
        return existing
    amount = money(amount)
    if amount < 0:
        raise ValueError("Ledger amounts are never negative; the direction is given by the wallets")
    _check_currency(from_wallet)
    _check_currency(to_wallet)
    tx = Transaction(
        id=uuid.uuid4(),
        idempotency_key=key,
        type=type.value,
        status=status.value,
        amount=amount,
        from_wallet=from_wallet.id if from_wallet else None,
        to_wallet=to_wallet.id if to_wallet else None,
        reference=reference,
        description=description,
        deployment_id=deployment_id,
        settled_at=utcnow() if status == TransactionStatus.SETTLED else None,
    )
    db.add(tx)
    await db.flush()  # the unique key rejects a concurrent duplicate before balances move
    if from_wallet is not None and status.value in DEBIT_STATES:
        await _adjust(db, from_wallet.id, -amount)
    if to_wallet is not None and status == TransactionStatus.SETTLED:
        await _adjust(db, to_wallet.id, amount)
    return tx


async def settle(db: AsyncSession, tx: Transaction) -> bool:
    """PENDING -> SETTLED. The debit already applied; the credit applies now. False if not PENDING."""
    result = await db.execute(
        update(Transaction)
        .where(Transaction.id == tx.id, Transaction.status == TransactionStatus.PENDING.value)
        .values(status=TransactionStatus.SETTLED.value, settled_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if rowcount(result) != 1:
        return False
    if tx.to_wallet is not None:
        await _adjust(db, tx.to_wallet, Decimal(tx.amount))
    tx.status = TransactionStatus.SETTLED.value
    return True


async def fail(db: AsyncSession, tx: Transaction) -> bool:
    """PENDING -> FAILED: the held debit is returned to the payer. False if not PENDING."""
    result = await db.execute(
        update(Transaction)
        .where(Transaction.id == tx.id, Transaction.status == TransactionStatus.PENDING.value)
        .values(status=TransactionStatus.FAILED.value)
        .execution_options(synchronize_session=False)
    )
    if rowcount(result) != 1:
        return False
    if tx.from_wallet is not None:
        await _adjust(db, tx.from_wallet, Decimal(tx.amount))
    tx.status = TransactionStatus.FAILED.value
    return True


async def balance(db: AsyncSession, wallet_id: uuid.UUID) -> Decimal:
    value = (await db.execute(select(Wallet.balance).where(Wallet.id == wallet_id))).scalar()
    return Decimal(value or 0)
