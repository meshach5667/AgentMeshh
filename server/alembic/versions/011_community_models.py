"""community models: customer-imported Hugging Face GGUF models and the provider opt-in to serve them

Revision ID: 011
Revises: 010
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("models", sa.Column("owner_customer_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_models_owner_customer", "models", "customers", ["owner_customer_id"], ["id"])
    op.create_index("ix_models_owner_customer_id", "models", ["owner_customer_id"])
    op.add_column("models", sa.Column("source_url", sa.String(500), nullable=True))
    op.add_column("models", sa.Column("withdrawn_at", sa.DateTime(), nullable=True))
    op.add_column(
        "nodes", sa.Column("accepts_community_models", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("nodes", "accepts_community_models")
    op.drop_column("models", "withdrawn_at")
    op.drop_column("models", "source_url")
    op.drop_index("ix_models_owner_customer_id", table_name="models")
    op.drop_constraint("fk_models_owner_customer", "models", type_="foreignkey")
    op.drop_column("models", "owner_customer_id")
