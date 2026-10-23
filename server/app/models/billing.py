"""Pricing, rated charges, Paystack payments (top-ups), webhook inbox, and provider payouts.

Measured usage (usage_records, deployment lifecycle events) is kept separate from what is charged: a Charge
records the quantities it priced, the pricing version used, and the ledger amounts it produced.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow

MONEY = Numeric(18, 8)


class PricingRule(Base):
    """One immutable price list version. The active rule is the newest whose effective_from has passed."""

    __tablename__ = "pricing_rules"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cpu_core_hour: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    ram_gb_hour: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    vram_gb_hour: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    input_tokens_per_million: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    output_tokens_per_million: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    platform_fee_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Charge(Base):
    """What a deployment was charged for one billing window on one node, priced with one pricing version."""

    __tablename__ = "charges"
    __table_args__ = (
        UniqueConstraint("deployment_id", "node_id", "period_start", name="uq_charges_deployment_node_period"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=False, index=True
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"), index=True)
    customer_wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False, index=True
    )
    provider_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallets.id"), index=True
    )
    pricing_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pricing_rules.id"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Measured quantities (snapshot): READY time from lifecycle events, reservation from the scheduler,
    # tokens as reported by the runtime.
    ready_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ram_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vram_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    token_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    provider_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    platform_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class PaymentStatus(str, enum.Enum):  # noqa: UP042
    INITIALIZED = "INITIALIZED"  # checkout created, customer has not paid (yet)
    SUCCEEDED = "SUCCEEDED"  # verified and credited exactly once
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"
    REVIEW = "REVIEW"  # Paystack reported success but amount/currency did not match; not credited


class Payment(Base):
    """A customer top-up through Paystack. Credited to the wallet only once, on verified success."""

    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="paystack")
    reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PaymentStatus.INITIALIZED.value, index=True)
    provider_status: Mapped[str | None] = mapped_column(String(30))
    authorization_url: Mapped[str | None] = mapped_column(String(500))
    channel: Mapped[str | None] = mapped_column(String(30))
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transactions.id"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class PaymentEvent(Base):
    """Webhook inbox. The unique event_key makes redelivered webhooks no-ops. Payloads are not stored (they
    contain customer contact and card details); only what is needed to trace processing."""

    __tablename__ = "payment_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    event_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), index=True)
    outcome: Mapped[str | None] = mapped_column(String(60))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class PayoutAccount(Base):
    """A provider's Paystack transfer recipient. Only the last four digits of the account are kept."""

    __tablename__ = "payout_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="paystack")
    recipient_code: Mapped[str] = mapped_column(String(100), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(20), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(200))
    account_name: Mapped[str | None] = mapped_column(String(200))
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class PayoutStatus(str, enum.Enum):  # noqa: UP042
    REQUESTED = "REQUESTED"  # funds held; waiting for operator approval
    PENDING = "PENDING"  # transfer initiated (or outcome unknown); waiting for Paystack
    OTP_REQUIRED = "OTP_REQUIRED"  # Paystack wants an OTP; the operator must finalize or disable OTP
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"  # funds returned to the wallet
    REVERSED = "REVERSED"  # funds returned to the wallet
    REJECTED = "REJECTED"  # declined by an operator; funds returned


class Payout(Base):
    __tablename__ = "payouts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False)
    payout_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payout_accounts.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PayoutStatus.REQUESTED.value, index=True)
    transfer_code: Mapped[str | None] = mapped_column(String(100))
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("transactions.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Set when reconciliation confirmed Paystack's record of the transfer matches ours.
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
