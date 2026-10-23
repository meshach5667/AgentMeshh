import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow


class UsageRecord(Base):
    """Metering record. kind="inference" rows describe one gateway request; kind="resource" rows describe
    resource consumption over a period. Prompt and response contents are never stored."""

    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("request_id", name="uq_usage_records_request_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workload_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workloads.id"), index=True)
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id"), index=True
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"))
    gpu_seconds: Mapped[float | None] = mapped_column(Float, default=0)
    cpu_seconds: Mapped[float | None] = mapped_column(Float, default=0)
    storage_usage: Mapped[float | None] = mapped_column(Float, default=0)
    bandwidth_usage: Mapped[float | None] = mapped_column(Float, default=0)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime)
    period_end: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)

    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="resource")
    # Gateway-generated request id; unique so a retried metering write cannot double count.
    request_id: Mapped[str | None] = mapped_column(String(64))
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("api_keys.id"))
    endpoint: Mapped[str | None] = mapped_column(String(100))
    status_code: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(30))  # success | runtime_error | cancelled | timeout | ...
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    # "runtime_reported": counts come from the model runtime on a provider node and are not independently
    # verified. NULL counts mean the runtime did not report them; they are never estimated.
    token_source: Mapped[str | None] = mapped_column(String(30))
    response_bytes: Mapped[int | None] = mapped_column(Integer)
