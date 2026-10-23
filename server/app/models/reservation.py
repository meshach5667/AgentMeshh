import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow


class ResourceReservation(Base):
    """Capacity held on a node for a deployment. A deployment that is moved to another node keeps its old,
    RELEASED rows as history; a partial unique index allows at most one ACTIVE row per deployment."""

    __tablename__ = "resource_reservations"
    __table_args__ = (
        Index(
            "uq_resource_reservations_active",
            "deployment_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=False, index=True
    )
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"), nullable=False, index=True)
    cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ram_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disk_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vram_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE | RELEASED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
