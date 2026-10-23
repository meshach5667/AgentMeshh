"""billing and payments: versioned pricing, rated charges, Paystack top-ups and payouts, idempotent ledger

No prices are seeded: pricing is an operator decision (POST /admin/pricing). Until a rule exists, usage is
measured but not charged.

Revision ID: 009
Revises: 008
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from app.core.config import settings

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 8)


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _fk(name: str, target: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey(target), nullable=nullable)


def upgrade() -> None:
    op.add_column("transactions", sa.Column("idempotency_key", sa.String(160), nullable=True))
    op.add_column("transactions", sa.Column("settled_at", sa.DateTime(), nullable=True))
    op.create_unique_constraint("uq_transactions_idempotency_key", "transactions", ["idempotency_key"])
    op.add_column("deployments", sa.Column("metered_until", sa.DateTime(), nullable=True))
    op.add_column("deployment_events", _fk("node_id", "nodes.id"))
    # Existing events predate per-event node tracking; the deployment's current node is the best record.
    op.execute(
        "UPDATE deployment_events SET node_id = (SELECT d.node_id FROM deployments d "
        "WHERE d.id = deployment_events.deployment_id)"
    )
    # Before this migration no payment path existed, so every wallet balance is unpaid test credit. Relabel
    # wallets into the billing currency so the ledger (which refuses mixed currencies) can use them.
    op.execute(f"UPDATE wallets SET currency = '{settings.BILLING_CURRENCY}'")
    # Usage before billing existed is not charged retroactively.
    op.execute("UPDATE deployments SET metered_until = (now() AT TIME ZONE 'utc')")

    op.create_table(
        "pricing_rules",
        _id(),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cpu_core_hour", MONEY, nullable=False),
        sa.Column("ram_gb_hour", MONEY, nullable=False),
        sa.Column("vram_gb_hour", MONEY, nullable=False),
        sa.Column("input_tokens_per_million", MONEY, nullable=False),
        sa.Column("output_tokens_per_million", MONEY, nullable=False),
        sa.Column("platform_fee_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.String(500)),
        _fk("created_by", "users.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pricing_rules_effective_from", "pricing_rules", ["effective_from"])

    op.create_table(
        "charges",
        _id(),
        _fk("deployment_id", "deployments.id", nullable=False),
        _fk("node_id", "nodes.id"),
        _fk("customer_wallet_id", "wallets.id", nullable=False),
        _fk("provider_wallet_id", "wallets.id"),
        _fk("pricing_rule_id", "pricing_rules.id", nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("ready_seconds", sa.Float(), nullable=False),
        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("ram_mb", sa.Integer(), nullable=False),
        sa.Column("vram_mb", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("resource_amount", MONEY, nullable=False),
        sa.Column("token_amount", MONEY, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("provider_amount", MONEY, nullable=False),
        sa.Column("platform_fee", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("deployment_id", "node_id", "period_start", name="uq_charges_deployment_node_period"),
    )
    for col in ("deployment_id", "node_id", "customer_wallet_id", "provider_wallet_id", "created_at"):
        op.create_index(f"ix_charges_{col}", "charges", [col])

    op.create_table(
        "payments",
        _id(),
        _fk("user_id", "users.id", nullable=False),
        _fk("wallet_id", "wallets.id", nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False, unique=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_status", sa.String(30)),
        sa.Column("authorization_url", sa.String(500)),
        sa.Column("channel", sa.String(30)),
        sa.Column("failure_reason", sa.String(300)),
        _fk("transaction_id", "transactions.id"),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    op.create_table(
        "payment_events",
        _id(),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("event_key", sa.String(200), nullable=False, unique=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("reference", sa.String(100)),
        sa.Column("outcome", sa.String(60)),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime()),
    )
    op.create_index("ix_payment_events_reference", "payment_events", ["reference"])

    op.create_table(
        "payout_accounts",
        _id(),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("recipient_code", sa.String(100), nullable=False),
        sa.Column("bank_code", sa.String(20), nullable=False),
        sa.Column("bank_name", sa.String(200)),
        sa.Column("account_name", sa.String(200)),
        sa.Column("account_last4", sa.String(4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "payouts",
        _id(),
        _fk("user_id", "users.id", nullable=False),
        _fk("wallet_id", "wallets.id", nullable=False),
        _fk("payout_account_id", "payout_accounts.id", nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("transfer_code", sa.String(100)),
        sa.Column("failure_reason", sa.String(300)),
        _fk("transaction_id", "transactions.id"),
        _fk("decided_by", "users.id"),
        sa.Column("decided_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("reconciled_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payouts_user_id", "payouts", ["user_id"])
    op.create_index("ix_payouts_status", "payouts", ["status"])


def downgrade() -> None:
    op.drop_table("payouts")
    op.drop_table("payout_accounts")
    op.drop_table("payment_events")
    op.drop_table("payments")
    op.drop_table("charges")
    op.drop_table("pricing_rules")
    op.drop_column("deployment_events", "node_id")
    op.drop_column("deployments", "metered_until")
    op.drop_constraint("uq_transactions_idempotency_key", "transactions", type_="unique")
    op.drop_column("transactions", "settled_at")
    op.drop_column("transactions", "idempotency_key")
