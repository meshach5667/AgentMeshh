import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow


class DeploymentStatus(str, enum.Enum):  # noqa: UP042
    """Lifecycle states. Valid transitions are defined in app.services.deployment_lifecycle."""

    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    PROVISIONING = "PROVISIONING"
    STARTING = "STARTING"
    READY = "READY"
    UNHEALTHY = "UNHEALTHY"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (UniqueConstraint("customer_id", "idempotency_key", name="uq_deployments_customer_idempotency"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("models.id"))
    node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"))
    status: Mapped[str] = mapped_column(String(50), default=DeploymentStatus.REQUESTED, index=True, nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(500))
    config: Mapped[Any] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=True)

    runtime: Mapped[str | None] = mapped_column(String(50))
    model_tag: Mapped[str | None] = mapped_column(String(255))
    model_digest: Mapped[str | None] = mapped_column(String(255))  # reported by the worker after pulling
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime)
    was_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cleanup_status: Mapped[str | None] = mapped_column(String(50))  # pending | done | pending_node
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # Placement history: how many nodes this deployment has been scheduled onto, and which nodes failed it.
    schedule_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_node_ids: Mapped[Any] = mapped_column(JSON, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("model_artifacts.id"))
    # Billing watermark: READY time and tokens before this instant have been rated into charges.
    metered_until: Mapped[datetime | None] = mapped_column(DateTime)


class DeploymentEvent(Base):
    """Append-only lifecycle history, shown to customers for progress and troubleshooting."""

    __tablename__ = "deployment_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str | None] = mapped_column(String(50))
    actor: Mapped[str] = mapped_column(String(50), nullable=False)  # customer | worker | system | operator
    # Node the deployment was placed on when the event happened (billing attributes READY time by it).
    node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"))
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
