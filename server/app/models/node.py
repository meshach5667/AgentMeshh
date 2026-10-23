from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow

if TYPE_CHECKING:
    from app.models.user import Provider


class NodeStatus(str, enum.Enum):  # noqa: UP042
    REGISTERING = "REGISTERING"
    ONLINE = "ONLINE"
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class NodeMode(str, enum.Enum):  # noqa: UP042
    DOCKER = "docker"  # Docker-based worker managing workload containers
    AGENT = "agent"  # installable agent managing dedicated runtime processes


def _capacity() -> Any:
    return mapped_column(Integer, nullable=False, default=0)


class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255))
    public_key: Mapped[str | None] = mapped_column(Text)
    api_key_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(50), default=NodeStatus.REGISTERING, index=True)
    region: Mapped[str | None] = mapped_column(String(100))
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
    reputation_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=100.00)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    # Worker identity and protocol
    mode: Mapped[str | None] = mapped_column(String(20))
    worker_version: Mapped[str | None] = mapped_column(String(50))
    protocol_version: Mapped[int | None] = mapped_column(Integer)
    runtimes: Mapped[Any] = mapped_column(JSON, nullable=True)  # [{"name": "ollama", "backend": ..., ...}]
    # Set by the provider in the dashboard (pause/resume).
    accepting_workloads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Provider opt-in to unreviewed community models imported by customers. Off unless the provider turns it on.
    accepts_community_models: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Reported by the worker itself: local pause/drain or outside its availability schedule.
    worker_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    worker_unavailable_reason: Mapped[str | None] = mapped_column(String(50))
    last_metrics: Mapped[Any] = mapped_column(JSON, nullable=True)

    # Capacity the provider has explicitly allocated to AgentMesh (never the whole machine by default),
    # and capacity currently reserved by deployments. Reservations are changed only with atomic
    # conditional UPDATEs in app.services.scheduler_service.
    allocated_cpu_cores: Mapped[int] = _capacity()
    allocated_ram_mb: Mapped[int] = _capacity()
    allocated_disk_mb: Mapped[int] = _capacity()
    allocated_vram_mb: Mapped[int] = _capacity()
    reserved_cpu_cores: Mapped[int] = _capacity()
    reserved_ram_mb: Mapped[int] = _capacity()
    reserved_disk_mb: Mapped[int] = _capacity()
    reserved_vram_mb: Mapped[int] = _capacity()

    owner: Mapped[Provider] = relationship(back_populates="nodes")
    hardware: Mapped[NodeHardware | None] = relationship(back_populates="node", uselist=False)
    pricing: Mapped[NodePricing | None] = relationship(back_populates="node", uselist=False)


class NodeHardware(Base):
    __tablename__ = "node_hardware"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"), unique=True, nullable=False)
    cpu_model: Mapped[str | None] = mapped_column(String(255))
    cpu_cores: Mapped[int | None] = mapped_column(Integer)
    ram_gb: Mapped[int | None] = mapped_column(Integer)
    storage_gb: Mapped[int | None] = mapped_column(Integer)
    gpu_model: Mapped[str | None] = mapped_column(String(255))
    gpu_count: Mapped[int | None] = mapped_column(Integer, default=0)
    gpu_vram_gb: Mapped[int | None] = mapped_column(Integer)
    os_info: Mapped[str | None] = mapped_column(String(255))
    capabilities: Mapped[Any] = mapped_column(JSON, nullable=True)

    node: Mapped[Node] = relationship(back_populates="hardware")


class PricingMode(str, enum.Enum):  # noqa: UP042
    PROVIDER_FIXED = "PROVIDER_FIXED"
    AGENTMESH_RECOMMENDED = "AGENTMESH_RECOMMENDED"


class NodePricing(Base):
    __tablename__ = "node_pricing"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nodes.id"), unique=True, nullable=False)
    gpu_hour_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), default=0)
    cpu_hour_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), default=0)
    ram_gb_hour_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), default=0)
    storage_gb_month_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), default=0)
    bandwidth_gb_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), default=0)
    pricing_mode: Mapped[str | None] = mapped_column(String(50), default=PricingMode.PROVIDER_FIXED)
    currency: Mapped[str | None] = mapped_column(String(10), default="USD")

    node: Mapped[Node] = relationship(back_populates="pricing")
