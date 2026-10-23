import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow


class TransactionType(str, enum.Enum):  # noqa: UP042
    DEPOSIT = "DEPOSIT"
    COMPUTE_CHARGE = "COMPUTE_CHARGE"
    PROVIDER_CREDIT = "PROVIDER_CREDIT"
    PLATFORM_FEE = "PLATFORM_FEE"
    REFUND = "REFUND"
    PAYOUT = "PAYOUT"


class TransactionStatus(str, enum.Enum):  # noqa: UP042
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class Transaction(Base):
    """Ledger entry. Debits (from_wallet) apply while PENDING or SETTLED; credits (to_wallet) apply only when
    SETTLED. Every wallet balance therefore equals its settled credits minus its pending and settled debits,
    which reconciliation checks. ``idempotency_key`` makes each logical posting happen at most once."""

    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_wallet: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("wallets.id"), index=True)
    to_wallet: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("wallets.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(String(50))
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("deployments.id"))
    reference: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)
