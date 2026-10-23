"""Model catalog validation: which models can be deployed, on which runtimes, and with what resources.

Compatibility is explicit: a model is deployable on a runtime only through an enabled ModelArtifact for that
runtime whose source passes validation. Appearing in the catalog is never proof of deployability; the
artifact's ``last_ready_at`` records when serving it last actually worked.
"""

import math
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.models.model import Model, ModelArtifact

# Runtimes the control plane can schedule, in default preference order (most widely available first).
RUNTIME_PREFERENCE = ("ollama", "llamacpp", "vllm")
SUPPORTED_RUNTIMES = frozenset(RUNTIME_PREFERENCE)

# Ollama model references: optional namespace, name, optional tag. No URLs, paths, or shell metacharacters.
OLLAMA_TAG_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]{0,63}(/[a-z0-9][a-z0-9._-]{0,63})?(:[a-zA-Z0-9][a-zA-Z0-9._-]{0,63})?$"
)
HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
HF_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
GGUF_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.gguf$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

MAX_NUM_CTX = 8192
DEFAULT_NUM_CTX = 2048


class DeploymentConfig(BaseModel):
    """Allowlisted deployment options. Unknown keys are rejected rather than passed to the runtime."""

    model_config = ConfigDict(extra="forbid")

    num_ctx: int = Field(DEFAULT_NUM_CTX, ge=512, le=MAX_NUM_CTX, description="Context window in tokens")
    region: str | None = Field(None, max_length=100)
    require_gpu: bool = False


@dataclass(frozen=True)
class ResourceRequest:
    runtime: str
    cpu_cores: int
    ram_mb: int
    disk_mb: int
    vram_mb: int
    gpu_required: bool
    region: str | None = None
    community: bool = False  # unreviewed community model: only nodes whose provider opted in


def validate_model_tag(tag: str | None) -> str:
    if not tag or not OLLAMA_TAG_RE.fullmatch(tag):
        raise HTTPException(status_code=422, detail="Model has no valid runtime identifier")
    return tag


def artifact_problem(a: ModelArtifact) -> str | None:
    """Why an artifact cannot be deployed, or None if it is valid. Mirrors the worker's own validation."""
    if a.runtime not in SUPPORTED_RUNTIMES:
        return f"runtime '{a.runtime}' is not supported"
    if a.runtime == "ollama":
        if a.source_type != "ollama" or not OLLAMA_TAG_RE.fullmatch(a.reference or ""):
            return "invalid Ollama tag"
        return None
    if a.source_type != "huggingface" or not HF_REPO_RE.fullmatch(a.reference or ""):
        return "invalid Hugging Face repository"
    if not HF_REVISION_RE.fullmatch(a.revision or ""):
        return "Hugging Face revision must be pinned to a commit"
    if a.runtime == "llamacpp":
        if not GGUF_FILE_RE.fullmatch(a.file or "") or not SHA256_RE.fullmatch(a.sha256 or ""):
            return "llama.cpp artifacts need a GGUF file name and its SHA-256"
    if a.runtime == "vllm" and not a.gpu_required:
        return "vLLM artifacts must require a GPU"
    return None


def is_unreviewed(model: Model) -> bool:
    """A customer-imported model no operator has approved."""
    return model.owner_customer_id is not None and not model.is_approved


async def get_deployable_model(db: AsyncSession, model_id, customer_id=None) -> Model:
    """An approved catalog model, or the caller's own community model. Others' community models are 404."""
    model = await db.get(Model, parse_uuid(model_id, "Model"))
    if (
        model is None
        or model.withdrawn_at is not None
        or not (model.is_approved or (customer_id is not None and model.owner_customer_id == customer_id))
    ):
        raise HTTPException(status_code=404, detail="Approved model not found")
    return model


async def deployable_artifacts(db: AsyncSession, model: Model, runtime: str | None = None) -> list[ModelArtifact]:
    """Enabled, valid artifacts for ``model`` in preference order (or only ``runtime`` if given)."""
    if runtime is not None and runtime not in SUPPORTED_RUNTIMES:
        raise HTTPException(
            status_code=422, detail=f"Unknown runtime '{runtime}'. Supported: {', '.join(RUNTIME_PREFERENCE)}"
        )
    rows = (
        (await db.execute(select(ModelArtifact).where(ModelArtifact.model_id == model.id, ModelArtifact.is_enabled)))
        .scalars()
        .all()
    )
    valid = [a for a in rows if artifact_problem(a) is None]
    offered = sorted({a.runtime for a in valid}, key=RUNTIME_PREFERENCE.index)
    if runtime is not None:
        valid = [a for a in valid if a.runtime == runtime]
    if not valid:
        if runtime is not None and offered:
            detail = f"Model is not available on runtime '{runtime}'. Available runtimes: {', '.join(offered)}"
        else:
            detail = "Model has no deployable runtime artifact"
        raise HTTPException(status_code=422, detail=detail)
    return sorted(valid, key=lambda a: RUNTIME_PREFERENCE.index(a.runtime))


def estimate_requirements(
    artifact: ModelArtifact, config: DeploymentConfig, *, community: bool = False
) -> ResourceRequest:
    """Scheduler reservation for an artifact. Catalog figures assume the default context; larger contexts
    need more KV-cache memory, approximated at 128 MB per extra 2048 tokens. These are estimates."""
    extra_ctx_mb = max(0, math.ceil((config.num_ctx - DEFAULT_NUM_CTX) / 2048)) * 128
    gpu = bool(artifact.gpu_required or config.require_gpu)
    return ResourceRequest(
        runtime=artifact.runtime,
        cpu_cores=max(1, artifact.min_cpu_cores or 1),
        ram_mb=artifact.min_ram_mb + extra_ctx_mb,
        disk_mb=artifact.min_disk_mb,
        vram_mb=(artifact.min_vram_mb or 0) + (extra_ctx_mb if gpu else 0) if gpu else 0,
        gpu_required=gpu,
        region=config.region,
        community=community,
    )


def worker_source(artifact: ModelArtifact) -> dict | None:
    """The source description sent to the worker (validated again there)."""
    if artifact.source_type != "huggingface":
        return None
    source: dict[str, Any] = {"type": "huggingface", "repo": artifact.reference, "revision": artifact.revision}
    if artifact.runtime == "llamacpp":
        source.update(file=artifact.file, sha256=artifact.sha256, size=artifact.size_bytes or 0)
    return source
