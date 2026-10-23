"""AI deployment agent: runs (persistent workflow state), their event history, the inference request queue
that internal inference machines pull from, and those machines' last reported health.

Workflow state lives here, not in the model conversation, so a run resumes after a control-plane restart
and a deployment keeps running while the inference machine is offline.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutil import utcnow


class AiRun(Base):
    """One natural-language deployment request and everything the agent did for it. Valid status changes are
    defined in app.services.ai.workflow."""

    __tablename__ = "ai_runs"
    __table_args__ = (UniqueConstraint("customer_id", "idempotency_key", name="uq_ai_runs_customer_idempotency"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_text: Mapped[str] = mapped_column(Text, nullable=False)  # the customer's own words (untrusted)
    limits: Mapped[Any] = mapped_column(JSON, nullable=False)  # validated AutonomyLimits
    plan: Mapped[Any] = mapped_column(JSON, nullable=True)  # validated DeploymentPlan
    # Current deployment, and every deployment this run created (recovery creates new ones).
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("deployments.id"))
    deployment_ids: Mapped[Any] = mapped_column(JSON, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3))
    estimated_hourly: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    estimated_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    # Agent bookkeeping. ``conversation`` is the bounded transcript of the current planning or diagnosis
    # conversation; ``pending_request_id`` is the inference request the run is waiting for.
    phase: Mapped[str | None] = mapped_column(String(20))  # planning | recovery
    conversation: Mapped[Any] = mapped_column(JSON, nullable=True)
    pending_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probe_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Latest model-written explanation for the customer. Always shown as AI-generated, never as fact.
    explanation: Mapped[str | None] = mapped_column(Text)
    endpoint: Mapped[str | None] = mapped_column(String(500))  # published only after a verified inference
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stop_reason: Mapped[str | None] = mapped_column(String(100))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime)  # max duration, from first submission
    # Processing lease so only one API replica advances a run at a time.
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiRunEvent(Base):
    """Append-only history of a run: state changes, tool calls, AI decisions, and waits."""

    __tablename__ = "ai_run_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # state | tool | ai | info | error
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    message: Mapped[str | None] = mapped_column(Text)
    data: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AiInferenceRequest(Base):
    """One model call, waiting for an inference machine to lease it. Prompts are stored only until answered."""

    __tablename__ = "ai_inference_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)  # planning | recovery
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)  # messages, output schema, options
    # PENDING | LEASED | COMPLETED | FAILED | EXPIRED | CANCELLED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    node_id: Mapped[str | None] = mapped_column(String(64))  # inference machine holding/answering it
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)  # {"content": ..., token counts}
    error_code: Mapped[str | None] = mapped_column(String(50))
    error: Mapped[str | None] = mapped_column(String(500))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiInferenceNode(Base):
    """Last heartbeat from an internal inference machine. Not a provider node: it never runs customer work."""

    __tablename__ = "ai_inference_nodes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # AI_INFERENCE_NODE_ID
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    model: Mapped[str | None] = mapped_column(String(255))
    ollama_version: Mapped[str | None] = mapped_column(String(50))
    ollama_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(200))  # why it is not accepting work
    metrics: Mapped[Any] = mapped_column(JSON, nullable=True)  # cpu/memory/load, numbers only
    in_flight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
