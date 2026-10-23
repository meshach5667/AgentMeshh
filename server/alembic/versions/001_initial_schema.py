"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users table
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )

    # providers table
    op.create_table(
        "providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("payout_status", sa.String(50), default="pending"),
        sa.Column("balance", sa.Numeric(18, 8), default=0),
        sa.Column("created_at", sa.DateTime()),
    )

    # customers table
    op.create_table(
        "customers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime()),
    )

    # nodes table
    op.create_table(
        "nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("public_key", sa.Text()),
        sa.Column("api_key_hash", sa.String(255)),
        sa.Column("status", sa.String(50), default="REGISTERING"),
        sa.Column("region", sa.String(100)),
        sa.Column("last_heartbeat", sa.DateTime()),
        sa.Column("reputation_score", sa.Numeric(5, 2), default=100.00),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_nodes_status", "nodes", ["status"])
    op.create_index("ix_nodes_owner_id", "nodes", ["owner_id"])

    # node_hardware table
    op.create_table(
        "node_hardware",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id"), unique=True, nullable=False),
        sa.Column("cpu_model", sa.String(255)),
        sa.Column("cpu_cores", sa.Integer()),
        sa.Column("ram_gb", sa.Integer()),
        sa.Column("storage_gb", sa.Integer()),
        sa.Column("gpu_model", sa.String(255)),
        sa.Column("gpu_count", sa.Integer(), default=0),
        sa.Column("gpu_vram_gb", sa.Integer()),
        sa.Column("os_info", sa.String(255)),
        sa.Column("capabilities", JSON()),
    )

    # node_pricing table
    op.create_table(
        "node_pricing",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id"), unique=True, nullable=False),
        sa.Column("gpu_hour_price", sa.Numeric(10, 4), default=0),
        sa.Column("cpu_hour_price", sa.Numeric(10, 4), default=0),
        sa.Column("ram_gb_hour_price", sa.Numeric(10, 6), default=0),
        sa.Column("storage_gb_month_price", sa.Numeric(10, 4), default=0),
        sa.Column("bandwidth_gb_price", sa.Numeric(10, 4), default=0),
        sa.Column("pricing_mode", sa.String(50), default="PROVIDER_FIXED"),
        sa.Column("currency", sa.String(10), default="USD"),
    )

    # models table (AI models)
    op.create_table(
        "models",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(50)),
        sa.Column("runtime", sa.String(50)),
        sa.Column("source", sa.String(500)),
        sa.Column("minimum_vram", sa.Integer()),
        sa.Column("minimum_ram", sa.Integer()),
        sa.Column("minimum_cpu", sa.Integer()),
        sa.Column("storage_requirement", sa.Integer()),
        sa.Column("supported_gpu_families", JSON()),
        sa.Column("deployment_config", JSON()),
        sa.Column("is_approved", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime()),
    )

    # deployments table
    op.create_table(
        "deployments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id")),
        sa.Column("model_id", UUID(as_uuid=True), sa.ForeignKey("models.id")),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=True),
        sa.Column("status", sa.String(50), default="REQUESTED"),
        sa.Column("endpoint", sa.String(500)),
        sa.Column("config", JSON()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("ended_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_deployments_customer_id", "deployments", ["customer_id"])
    op.create_index("ix_deployments_status", "deployments", ["status"])

    # wallets table
    op.create_table(
        "wallets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True),
        sa.Column("balance", sa.Numeric(18, 8), default=0),
        sa.Column("currency", sa.String(10), default="USD"),
        sa.Column("created_at", sa.DateTime()),
    )

    # transactions table
    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("from_wallet", UUID(as_uuid=True), sa.ForeignKey("wallets.id"), nullable=True),
        sa.Column("to_wallet", UUID(as_uuid=True), sa.ForeignKey("wallets.id"), nullable=True),
        sa.Column("amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("type", sa.String(50)),
        sa.Column("status", sa.String(50)),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id"), nullable=True),
        sa.Column("reference", sa.String(255)),
        sa.Column("description", sa.String(500)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_transactions_from_wallet", "transactions", ["from_wallet"])
    op.create_index("ix_transactions_to_wallet", "transactions", ["to_wallet"])

    # usage_records table
    op.create_table(
        "usage_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id")),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id")),
        sa.Column("gpu_seconds", sa.Float(), default=0),
        sa.Column("cpu_seconds", sa.Float(), default=0),
        sa.Column("storage_usage", sa.Float(), default=0),
        sa.Column("bandwidth_usage", sa.Float(), default=0),
        sa.Column("total_cost", sa.Numeric(18, 8), default=0),
        sa.Column("period_start", sa.DateTime()),
        sa.Column("period_end", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_usage_records_deployment_id", "usage_records", ["deployment_id"])

    # agent_tasks table
    op.create_table(
        "agent_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(100)),
        sa.Column("status", sa.String(50)),
        sa.Column("input_data", JSON()),
        sa.Column("output_data", JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
    )

    # agent_actions table
    op.create_table(
        "agent_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("agent_tasks.id")),
        sa.Column("action", sa.String(100)),
        sa.Column("tool_name", sa.String(100)),
        sa.Column("tool_input", JSON()),
        sa.Column("tool_output", JSON()),
        sa.Column("reasoning", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )

    # audit_logs table
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100)),
        sa.Column("resource_type", sa.String(100)),
        sa.Column("resource_id", sa.String(100)),
        sa.Column("details", JSON()),
        sa.Column("ip_address", sa.String(50)),
        sa.Column("created_at", sa.DateTime()),
    )

    # events table
    op.create_table(
        "events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(100)),
        sa.Column("source", sa.String(100)),
        sa.Column("data", JSON()),
        sa.Column("created_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("audit_logs")
    op.drop_table("agent_actions")
    op.drop_table("agent_tasks")
    op.drop_table("usage_records")
    op.drop_table("transactions")
    op.drop_table("wallets")
    op.drop_table("deployments")
    op.drop_table("models")
    op.drop_table("node_pricing")
    op.drop_table("node_hardware")
    op.drop_table("nodes")
    op.drop_table("customers")
    op.drop_table("providers")
    op.drop_table("users")
