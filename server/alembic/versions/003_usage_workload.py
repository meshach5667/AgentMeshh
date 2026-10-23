"""link usage records to workloads

Revision ID: 003
Revises: 002
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usage_records", sa.Column("workload_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_usage_records_workload_id", "usage_records", "workloads", ["workload_id"], ["id"])
    op.create_index("ix_usage_records_workload_id", "usage_records", ["workload_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_workload_id", table_name="usage_records")
    op.drop_constraint("fk_usage_records_workload_id", "usage_records", type_="foreignkey")
    op.drop_column("usage_records", "workload_id")
