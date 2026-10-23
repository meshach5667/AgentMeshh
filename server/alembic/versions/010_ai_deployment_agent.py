"""AI deployment agent: runs, run events, the inference request queue, and inference machine health

Revision ID: 010
Revises: 009
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 8)


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "ai_runs",
        _id(),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON()),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id")),
        sa.Column("deployment_ids", sa.JSON()),
        sa.Column("currency", sa.String(3)),
        sa.Column("estimated_hourly", MONEY),
        sa.Column("estimated_total", MONEY),
        sa.Column("phase", sa.String(20)),
        sa.Column("conversation", sa.JSON()),
        sa.Column("pending_request_id", UUID(as_uuid=True)),
        sa.Column("agent_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("probe_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("explanation", sa.Text()),
        sa.Column("endpoint", sa.String(500)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stop_reason", sa.String(100)),
        sa.Column("deadline_at", sa.DateTime()),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.UniqueConstraint("customer_id", "idempotency_key", name="uq_ai_runs_customer_idempotency"),
    )
    op.create_table(
        "ai_run_events",
        _id(),
        sa.Column(
            "run_id", UUID(as_uuid=True), sa.ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("from_status", sa.String(30)),
        sa.Column("to_status", sa.String(30)),
        sa.Column("message", sa.Text()),
        sa.Column("data", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ai_inference_requests",
        _id(),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("node_id", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(50)),
        sa.Column("error", sa.String(500)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_table(
        "ai_inference_nodes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("model", sa.String(255)),
        sa.Column("ollama_version", sa.String(50)),
        sa.Column("ollama_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("accepting", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(200)),
        sa.Column("metrics", sa.JSON()),
        sa.Column("in_flight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ai_inference_nodes")
    op.drop_table("ai_inference_requests")
    op.drop_table("ai_run_events")
    op.drop_table("ai_runs")
