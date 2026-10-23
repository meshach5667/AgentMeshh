"""withdraw the placeholder catalog model seeded by 002

Migration 002 seeded an approved model named "agentmesh-controlled-mvp" backed by an echo stub
rather than a real runtime. It must not be offered as deployable. The row is unapproved instead of
deleted so existing workload rows that reference it keep their foreign key.

Revision ID: 004
Revises: 003
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

PLACEHOLDER_MODEL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

models = sa.table("models", sa.column("id", UUID(as_uuid=True)), sa.column("is_approved", sa.Boolean()))


def upgrade() -> None:
    op.execute(models.update().where(models.c.id == PLACEHOLDER_MODEL_ID).values(is_approved=False))


def downgrade() -> None:
    op.execute(models.update().where(models.c.id == PLACEHOLDER_MODEL_ID).values(is_approved=True))
