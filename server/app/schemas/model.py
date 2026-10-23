import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    runtime: str
    source_type: str
    reference: str
    revision: str | None = None
    file: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    format: str | None = None
    quantization: str | None = None
    min_ram_mb: int
    min_disk_mb: int
    min_vram_mb: int
    min_cpu_cores: int
    gpu_required: bool
    requirements_estimated: bool
    is_enabled: bool
    last_ready_at: datetime | None = None


class ModelOut(BaseModel):
    id: uuid.UUID
    name: str
    version: str | None = None
    runtime: str | None = None
    minimum_vram: int | None = None
    minimum_ram: int | None = None
    is_approved: bool
    model_tag: str | None = None
    publisher: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    format: str | None = None
    license: str | None = None
    context_length: int | None = None
    download_size_mb: int | None = None
    min_ram_mb: int | None = None
    min_disk_mb: int | None = None
    min_vram_mb: int | None = None
    min_cpu_cores: int | None = None
    gpu_required: bool = False
    requirements_estimated: bool = True
    source_url: str | None = None
    owner_customer_id: uuid.UUID | None = None
    artifacts: list[ArtifactOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_community(self) -> bool:
        """Imported by a customer and not reviewed by an operator."""
        return self.owner_customer_id is not None and not self.is_approved


class ModelCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(max_length=255)
    version: str = Field(max_length=50)
    runtime: str = Field(max_length=50)
    source: str = Field(max_length=500)
    minimum_vram: int = 0
    minimum_ram: int = 0
    minimum_cpu: int = 0
    storage_requirement: int = 0
    supported_gpu_families: dict[str, Any] = Field(default_factory=dict)
    deployment_config: dict[str, Any] = Field(default_factory=dict)

    model_tag: str | None = Field(None, max_length=255)
    publisher: str | None = Field(None, max_length=255)
    family: str | None = Field(None, max_length=100)
    parameter_size: str | None = Field(None, max_length=50)
    quantization: str | None = Field(None, max_length=50)
    format: str | None = Field(None, max_length=50)
    license: str | None = Field(None, max_length=255)
    context_length: int | None = Field(None, ge=1)
    download_size_mb: int | None = Field(None, ge=0)
    min_ram_mb: int | None = Field(None, ge=1)
    min_disk_mb: int | None = Field(None, ge=1)
    min_vram_mb: int | None = Field(None, ge=0)
    min_cpu_cores: int | None = Field(None, ge=1)
    gpu_required: bool = False
    requirements_estimated: bool = True

    @field_validator("model_tag")
    @classmethod
    def _valid_tag(cls, v: str | None) -> str | None:
        from app.services.catalog_service import OLLAMA_TAG_RE

        if v is not None and not OLLAMA_TAG_RE.fullmatch(v):
            raise ValueError("model_tag must be a plain runtime model reference such as 'qwen2.5:0.5b'")
        return v


class ArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime: Literal["ollama", "llamacpp", "vllm"]
    source_type: Literal["ollama", "huggingface"]
    reference: str = Field(max_length=255)
    revision: str | None = Field(None, max_length=64)
    file: str | None = Field(None, max_length=255)
    sha256: str | None = Field(None, max_length=64)
    size_bytes: int | None = Field(None, ge=0)
    format: Literal["ollama", "gguf", "safetensors"] | None = None
    quantization: str | None = Field(None, max_length=50)
    min_ram_mb: int = Field(ge=64)
    min_disk_mb: int = Field(ge=1)
    min_vram_mb: int = Field(0, ge=0)
    min_cpu_cores: int = Field(1, ge=1)
    gpu_required: bool = False
    requirements_estimated: bool = True


class ArtifactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool


class CommunityModelImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str = Field(max_length=500, description="owner/name, or a huggingface.co link to the repository or file")
    file: str | None = Field(None, max_length=255, description="The .gguf file to deploy")
    revision: str | None = Field(None, max_length=100, description="Branch, tag, or commit. Defaults to main")
    accept_terms: bool = Field(
        False, description="The customer confirms they may use the model under its license and AgentMesh's terms"
    )


class GgufFileOut(BaseModel):
    name: str
    size_bytes: int
    quantization: str | None = None
    problem: str | None = None
    min_ram_mb: int
    min_disk_mb: int
    min_cpu_cores: int


class CommunityModelPreview(BaseModel):
    """What importing would create, before the customer commits to it."""

    repo: str
    revision: str
    license: str | None = None
    license_problem: str | None = None
    architecture: str | None = None
    context_length: int | None = None
    files: list[GgufFileOut]
