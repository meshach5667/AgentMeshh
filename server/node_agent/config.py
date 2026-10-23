import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKER_VERSION = "0.3.0"
PROTOCOL_VERSION = 1
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class WorkerSettings(BaseSettings):
    """Worker configuration. Environment variables use the AGENTMESH_ prefix, e.g. AGENTMESH_MAX_RAM_MB."""

    model_config = SettingsConfigDict(env_prefix="AGENTMESH_", env_file=None, extra="ignore")

    CONTROL_PLANE_URL: str = "http://localhost:8000"
    # Plain HTTP is only accepted for loopback hosts unless explicitly allowed (e.g. a private Compose network).
    ALLOW_INSECURE_CONTROL_PLANE: bool = False
    DATA_DIR: str = os.path.expanduser("~/.agentmesh/worker")
    MODE: str = "agent"  # "docker" (Docker worker) or "agent" (installable agent)
    RUNTIME_BACKEND: str = ""  # "docker" or "process"; defaults from MODE
    NODE_NAME: str = ""

    # When this machine accepts work (local time), e.g. "mon-fri 18:00-08:00, weekends 00:00-24:00".
    # Empty means always. Outside the schedule: "pause" stops new work but keeps running workloads;
    # "drain" also stops running workloads so AgentMesh moves them to other nodes.
    AVAILABILITY_SCHEDULE: str = ""
    OUTSIDE_SCHEDULE: str = "pause"

    # Resources the provider allows AgentMesh to use. Unset values fall back to conservative defaults
    # (half the CPU and RAM, at most 20 GB of disk, no GPU) - never the whole machine.
    MAX_CPU_CORES: int | None = None
    MAX_RAM_MB: int | None = None
    MAX_DISK_MB: int | None = None
    ALLOW_GPU: bool = False
    MAX_VRAM_MB: int | None = None

    # Model runtimes this worker offers (each still reports whether it can actually run here).
    ENABLED_RUNTIMES: str = "ollama,llamacpp,vllm"
    # Hosts model weights may be downloaded from (Hugging Face and its file CDNs). Every redirect is checked.
    ALLOWED_MODEL_HOSTS: str = "huggingface.co,*.huggingface.co,*.hf.co"

    # Process backend (installable agent)
    OLLAMA_BINARY: str = "ollama"
    LLAMA_SERVER_BINARY: str = "llama-server"
    VLLM_BINARY: str = "vllm"
    # Wrap runtime processes in a systemd user scope with MemoryMax/CPUQuota when available.
    PROCESS_CGROUP_LIMITS: bool = True

    # Docker backend. Pin the image by digest in production (AGENTMESH_OLLAMA_IMAGE=ollama/ollama@sha256:...).
    OLLAMA_IMAGE: str = "ollama/ollama:0.12.3"
    DOCKER_HOST: str = ""  # empty: docker-py defaults (DOCKER_HOST env or the local socket)
    WORKLOAD_NETWORK: str = ""  # set when the worker itself runs in a container on this network
    # Network used only while a workload downloads its model. With WORKLOAD_NETWORK set, serving workloads
    # have no internet access.
    EGRESS_NETWORK: str = ""
    MODELS_VOLUME: str = "agentmesh-models"
    # vLLM container for GPU nodes. Pin by digest in production. This default tag has not been verified.
    VLLM_IMAGE: str = "vllm/vllm-openai:v0.10.1"

    PULL_ATTEMPTS: int = 3  # tries per model download when failures look transient
    PULL_RETRY_BASE_SECONDS: float = 5.0
    # Base64 Ed25519 public key that signs worker releases. Without it, updates are refused.
    UPDATE_PUBLIC_KEY: str = ""
    # Apply signed updates automatically when idle (no workloads), then exit so the service restarts.
    AUTO_UPDATE: bool = False
    HEARTBEAT_INTERVAL_SECONDS: int = 15
    HEALTH_CHECK_INTERVAL_SECONDS: int = 30
    MAX_CONCURRENT_REQUESTS_PER_DEPLOYMENT: int = 4
    REQUEST_TIMEOUT_SECONDS: int = 600

    @model_validator(mode="after")
    def _check(self) -> "WorkerSettings":
        if self.MODE not in ("docker", "agent"):
            raise ValueError("AGENTMESH_MODE must be 'docker' or 'agent'")
        if not self.RUNTIME_BACKEND:
            self.RUNTIME_BACKEND = "docker" if self.MODE == "docker" else "process"
        if self.OUTSIDE_SCHEDULE not in ("pause", "drain"):
            raise ValueError("AGENTMESH_OUTSIDE_SCHEDULE must be 'pause' or 'drain'")
        from .schedule import parse

        parse(self.AVAILABILITY_SCHEDULE)  # fail fast on a malformed schedule
        if self.RUNTIME_BACKEND not in ("docker", "process"):
            raise ValueError("AGENTMESH_RUNTIME_BACKEND must be 'docker' or 'process'")
        url = urlparse(self.CONTROL_PLANE_URL)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ValueError("AGENTMESH_CONTROL_PLANE_URL must be an http(s) URL")
        if url.scheme == "http" and url.hostname not in LOCAL_HOSTS and not self.ALLOW_INSECURE_CONTROL_PLANE:
            raise ValueError(
                "Refusing plain HTTP to a non-local control plane. Use https:// or set "
                "AGENTMESH_ALLOW_INSECURE_CONTROL_PLANE=true for a trusted private network."
            )
        self.CONTROL_PLANE_URL = self.CONTROL_PLANE_URL.rstrip("/")
        return self

    @property
    def data_path(self) -> Path:
        return Path(self.DATA_DIR)


def default_config_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "agentmesh" / "worker.env"


def config_file() -> Path:
    return Path(os.environ.get("AGENTMESH_CONFIG_FILE") or default_config_file())


def load_settings(**overrides) -> WorkerSettings:
    """Settings from (lowest to highest priority): defaults, the config file written by the installer,
    AGENTMESH_* environment variables, explicit overrides."""
    path = config_file()
    if path.is_file():
        return WorkerSettings(_env_file=str(path), **overrides)  # type: ignore[call-arg]
    return WorkerSettings(**overrides)
