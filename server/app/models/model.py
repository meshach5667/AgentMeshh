import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow


class Model(Base):
    """Catalog entry. Appearing here does not make a model deployable: it must be approved, its runtime
    must be supported, and an eligible node with enough free capacity must exist at deploy time."""

    __tablename__ = "models"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(50))
    runtime: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str | None] = mapped_column(String(500))
    minimum_vram: Mapped[int | None] = mapped_column(Integer)
    minimum_ram: Mapped[int | None] = mapped_column(Integer)
    minimum_cpu: Mapped[int | None] = mapped_column(Integer)
    storage_requirement: Mapped[int | None] = mapped_column(Integer)
    supported_gpu_families: Mapped[Any] = mapped_column(JSON, nullable=True)
    deployment_config: Mapped[Any] = mapped_column(JSON, nullable=True)
    is_approved: Mapped[bool | None] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)

    # Runtime-specific identifier, e.g. an Ollama tag such as "qwen2.5:0.5b".
    model_tag: Mapped[str | None] = mapped_column(String(255), index=True)
    publisher: Mapped[str | None] = mapped_column(String(255))
    family: Mapped[str | None] = mapped_column(String(100))
    parameter_size: Mapped[str | None] = mapped_column(String(50))
    quantization: Mapped[str | None] = mapped_column(String(50))
    format: Mapped[str | None] = mapped_column(String(50))
    license: Mapped[str | None] = mapped_column(String(255))
    context_length: Mapped[int | None] = mapped_column(Integer)
    download_size_mb: Mapped[int | None] = mapped_column(Integer)
    # Resource requirements used by the scheduler. These are estimates unless stated otherwise.
    min_ram_mb: Mapped[int | None] = mapped_column(Integer)
    min_disk_mb: Mapped[int | None] = mapped_column(Integer)
    min_vram_mb: Mapped[int | None] = mapped_column(Integer)
    min_cpu_cores: Mapped[int | None] = mapped_column(Integer)
    gpu_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requirements_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Community models: imported by a customer from Hugging Face, visible and deployable only by that customer
    # while unapproved. Operator approval makes one a reviewed catalog entry.
    owner_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True
    )
    source_url: Mapped[str | None] = mapped_column(String(500))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)

    artifacts: Mapped[list["ModelArtifact"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class ModelArtifact(Base):
    """How one model is served by one runtime: where the weights come from (pinned), what they need, and
    whether serving them has actually worked. A model may have several (e.g. Ollama tag, GGUF for llama.cpp,
    safetensors for vLLM); compatibility is explicit, never assumed."""

    __tablename__ = "model_artifacts"
    __table_args__ = (UniqueConstraint("model_id", "runtime", name="uq_model_artifacts_model_runtime"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    runtime: Mapped[str] = mapped_column(String(20), nullable=False)  # ollama | llamacpp | vllm
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # ollama | huggingface
    # Ollama tag, or Hugging Face repository id. Also the name the model is served under.
    reference: Mapped[str] = mapped_column(String(255), nullable=False)
    revision: Mapped[str | None] = mapped_column(String(64))  # pinned Hugging Face commit
    file: Mapped[str | None] = mapped_column(String(255))  # GGUF file for llama.cpp
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    format: Mapped[str | None] = mapped_column(String(20))  # ollama | gguf | safetensors
    quantization: Mapped[str | None] = mapped_column(String(50))
    min_ram_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    min_disk_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    min_vram_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    gpu_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requirements_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set when a deployment of this artifact passes its readiness test: evidence it really works.
    last_ready_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
