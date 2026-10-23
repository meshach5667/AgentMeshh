import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.ai.policy import AutonomyLimits


class AiDeploymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: str = Field(min_length=5, max_length=2000, description="What to deploy, in your own words")
    limits: AutonomyLimits
    idempotency_key: str | None = Field(None, max_length=128)


class AiRunOut(BaseModel):
    id: uuid.UUID
    status: str
    request: str
    limits: dict[str, Any]
    plan: dict[str, Any] | None
    model_name: str | None
    deployment_id: uuid.UUID | None
    deployment_ids: list[str]
    deployment_status: str | None
    runtime: str | None
    endpoint: str | None = Field(description="Published only after a verified test completion")
    openai_base_url: str | None
    explanation: str | None = Field(description="Written by the AI model; informational only")
    error_code: str | None
    error_message: str | None
    currency: str | None
    estimated_hourly: Decimal | None
    estimated_total: Decimal | None
    actual_cost: Decimal
    recovery_attempts: int
    agent_steps: int
    tool_calls: int
    waiting_for_ai: bool
    cancel_requested: bool
    stop_reason: str | None
    deadline_at: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AiRunEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kind: str
    from_status: str | None
    to_status: str | None
    message: str | None
    data: dict[str, Any] | None
    created_at: datetime


class AiHealthOut(BaseModel):
    """What customers see. No hostnames, addresses, or credentials of the inference machine."""

    status: str
    available: bool
    model: str
    queue_depth: int
    message: str
    nodes: list[dict[str, Any]] | None = Field(None, description="Staff only")


# --- Inference adapter protocol ------------------------------------------------------------------------


class InferenceMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cpu_percent: float | None = Field(None, ge=0, le=100)
    load_per_cpu: float | None = Field(None, ge=0, le=1000)
    mem_available_mb: int | None = Field(None, ge=0)
    mem_total_mb: int | None = Field(None, ge=0)
    ollama_rss_mb: int | None = Field(None, ge=0)


class InferenceHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    model: str | None = Field(None, max_length=255)
    ollama_version: str | None = Field(None, max_length=50)
    ollama_ok: bool
    model_ready: bool
    accepting: bool
    reason: str | None = Field(None, max_length=200)
    in_flight: int = Field(0, ge=0, le=64)
    metrics: InferenceMetrics | None = None


class InferenceLeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_requests: int = Field(1, ge=1, le=16)
    wait_seconds: float = Field(0, ge=0, le=25)


class InferenceJob(BaseModel):
    id: uuid.UUID
    model: str
    messages: list[dict[str, Any]]
    format: dict[str, Any] | None
    options: dict[str, Any]
    timeout_seconds: int


class InferenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    content: str | None = Field(None, max_length=64_000)
    model: str | None = Field(None, max_length=255)
    error_code: str | None = Field(None, max_length=50)
    error: str | None = Field(None, max_length=2000)
    retryable: bool = False
    latency_ms: int | None = Field(None, ge=0)
    prompt_tokens: int | None = Field(None, ge=0)
    output_tokens: int | None = Field(None, ge=0)
