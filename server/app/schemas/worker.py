"""Worker protocol v1 message schemas (shared by the Docker worker and the installable agent).

Everything a worker reports is untrusted input: fields are bounded, unknown keys are rejected, and the
control plane clamps reported allocations to reported hardware.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL_VERSION = 1

_STRICT = ConfigDict(extra="forbid")


class GpuInfo(BaseModel):
    model_config = _STRICT
    vendor: str = Field(max_length=50)
    model: str = Field(max_length=200)
    vram_mb: int = Field(ge=0, le=1_048_576)


class HardwareReport(BaseModel):
    model_config = _STRICT
    os: str = Field(max_length=100)
    arch: str = Field(max_length=50)
    cpu_model: str = Field("", max_length=200)
    cpu_cores: int = Field(ge=1, le=4096)
    ram_mb: int = Field(ge=0, le=64 * 1024 * 1024)
    disk_free_mb: int = Field(ge=0, le=1024 * 1024 * 1024)
    gpus: list[GpuInfo] = Field(default_factory=list, max_length=16)


class Allocation(BaseModel):
    """Resources the provider explicitly allows AgentMesh to use on this machine."""

    model_config = _STRICT
    cpu_cores: int = Field(ge=0, le=4096)
    ram_mb: int = Field(ge=0, le=64 * 1024 * 1024)
    disk_mb: int = Field(ge=0, le=1024 * 1024 * 1024)
    vram_mb: int = Field(0, ge=0, le=1_048_576)


class RuntimeInfo(BaseModel):
    model_config = _STRICT
    name: Literal["ollama", "llamacpp", "vllm"]
    version: str = Field("", max_length=50)
    backend: Literal["docker", "process"]
    available: bool


class EnrollRequest(BaseModel):
    model_config = _STRICT
    token: str = Field(min_length=20, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    mode: Literal["docker", "agent"]
    worker_version: str = Field(max_length=50)
    protocol_version: int
    hardware: HardwareReport
    allocation: Allocation
    runtimes: list[RuntimeInfo] = Field(max_length=8)
    public_key: str | None = Field(None, max_length=4096)


class EnrollResponse(BaseModel):
    node_id: uuid.UUID
    node_credential: str
    protocol_version: int
    heartbeat_interval_seconds: int


class ReportedDeployment(BaseModel):
    model_config = _STRICT
    deployment_id: uuid.UUID
    state: Literal["provisioning", "starting", "running", "stopped", "failed"]
    healthy: bool = False


class HeartbeatRequest(BaseModel):
    model_config = _STRICT
    worker_version: str = Field(max_length=50)
    allocation: Allocation | None = None
    hardware: HardwareReport | None = None
    runtimes: list[RuntimeInfo] | None = Field(None, max_length=8)
    metrics: dict[str, float] = Field(default_factory=dict, max_length=32)
    deployments: list[ReportedDeployment] = Field(default_factory=list, max_length=256)
    # Local availability: False while paused, draining, or outside the provider's schedule.
    available: bool = True
    unavailable_reason: Literal["paused", "draining", "schedule"] | None = None

    @model_validator(mode="after")
    def _allocation_needs_hardware(self) -> "HeartbeatRequest":
        # Allocations are clamped to reported hardware, so both must arrive together.
        if self.allocation is not None and self.hardware is None:
            raise ValueError("allocation updates must include hardware")
        return self


class HeartbeatResponse(BaseModel):
    server_time: float
    accepting_workloads: bool
    heartbeat_interval_seconds: int
    # Deployments the worker reported but must not be running (stopped, deleted, or not assigned to it).
    stop_deployments: list[uuid.UUID]
    # Newest worker version announced by the operator, if any (see WORKER_RELEASE_MANIFEST).
    latest_worker_version: str | None = None


class PollRequest(BaseModel):
    model_config = _STRICT
    max_commands: int = Field(5, ge=1, le=20)
    wait_seconds: int = Field(20, ge=0, le=25)


class CommandOut(BaseModel):
    id: uuid.UUID
    type: str
    deployment_id: uuid.UUID | None
    payload: dict
    attempt: int


class PollResponse(BaseModel):
    commands: list[CommandOut]


class CommandAck(BaseModel):
    model_config = _STRICT
    status: Literal["accepted", "succeeded", "failed"]
    error: str | None = Field(None, max_length=1000)


class DeploymentStatusReport(BaseModel):
    model_config = _STRICT
    state: Literal["PROVISIONING", "STARTING", "READY", "FAILED", "STOPPED"]
    message: str | None = Field(None, max_length=500)
    error_code: str | None = Field(None, max_length=100, pattern=r"^[A-Z0-9_]+$")
    model_digest: str | None = Field(None, max_length=128, pattern=r"^[A-Za-z0-9:]+$")
