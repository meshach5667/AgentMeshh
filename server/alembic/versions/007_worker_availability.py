"""worker-reported availability (local pause/drain and availability schedules)

Revision ID: 007
Revises: 006
"""

import sqlalchemy as sa

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("worker_available", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("nodes", sa.Column("worker_unavailable_reason", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "worker_unavailable_reason")
    op.drop_column("nodes", "worker_available")
