"""add workloads

Revision ID: 002
Revises: 001
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "models",
            sa.column("id", UUID(as_uuid=True)),
            sa.column("name", sa.String()),
            sa.column("version", sa.String()),
            sa.column("runtime", sa.String()),
            sa.column("source", sa.String()),
            sa.column("is_approved", sa.Boolean()),
        ),
        [
            {
                "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
                "name": "agentmesh-controlled-mvp",
                "version": "1",
                "runtime": "controlled-mvp",
                "source": "builtin",
                "is_approved": True,
            }
        ],
    )
    op.create_table(
        "workloads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("model_id", UUID(as_uuid=True), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="QUEUED"),
        sa.Column("input_data", JSON(), nullable=False),
        sa.Column("result_data", JSON(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0"),
        sa.Column("tokens_out", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workloads_customer_id", "workloads", ["customer_id"])
    op.create_index("ix_workloads_status", "workloads", ["status"])


def downgrade() -> None:
    op.drop_index("ix_workloads_status", table_name="workloads")
    op.drop_index("ix_workloads_customer_id", table_name="workloads")
    op.drop_table("workloads")
    op.execute("DELETE FROM models WHERE id = '00000000-0000-0000-0000-000000000001'")
