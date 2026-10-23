import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.deployment import DeploymentStatus


class DeploymentCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: uuid.UUID
    runtime: Literal["ollama", "llamacpp", "vllm"] | None = Field(
        None, description="Serve with this runtime. Omit to let AgentMesh pick any compatible runtime"
    )
    config: dict[str, Any] = Field(default_factory=dict, description="num_ctx, region, require_gpu")
    idempotency_key: str | None = Field(
        None, max_length=128, description="Retries with the same key return the same deployment"
    )


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: uuid.UUID
    customer_id: uuid.UUID
    model_id: uuid.UUID
    node_id: uuid.UUID | None
    status: DeploymentStatus
    endpoint: str | None
    runtime: str | None = None
    model_tag: str | None = None
    model_digest: str | None = None
    config: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ready_at: datetime | None = None
    ended_at: datetime | None = None
    cleanup_status: str | None = None
    schedule_attempts: int = 0
    restart_count: int = 0
    artifact_id: uuid.UUID | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def openai_base_url(self) -> str | None:
        """OpenAI-compatible base URL; works for every runtime (append /chat/completions etc.)."""
        if not self.endpoint:
            return None
        return self.endpoint.rsplit("/", 1)[0] + "/v1"


class DeploymentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_status: str | None
    to_status: str | None
    actor: str
    message: str | None
    created_at: datetime
