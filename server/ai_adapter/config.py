"""Configuration of the AI inference adapter that runs on the internal inference machine (e.g. the HP 15).

Variables are read from the environment and from ~/.config/agentmesh/ai-adapter.env.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ADAPTER_VERSION = "0.1.0"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def config_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "agentmesh" / "ai-adapter.env"


class AdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Local Ollama. Loopback only unless explicitly allowed: Ollama has no authentication of its own.
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    ALLOW_REMOTE_OLLAMA: bool = False
    OLLAMA_MODEL: str = "gemma4:e2b-it-qat"
    # How long Ollama keeps the model in memory after a request, so it is loaded once and reused.
    OLLAMA_KEEP_ALIVE: str = "30m"

    # AgentMesh control plane, reached outbound (no public address or open port needed here).
    AGENTMESH_CONTROL_PLANE_URL: str = "http://localhost:8000"
    ALLOW_INSECURE_CONTROL_PLANE: bool = False
    AI_INFERENCE_TOKEN: str = ""
    AI_INFERENCE_NODE_ID: str = "hp15"

    # Conservative laptop defaults.
    AI_REQUEST_TIMEOUT: int = 180  # seconds per model call
    AI_MAX_CONCURRENT_REQUESTS: int = 1
    AI_NUM_CTX: int = 4096
    AI_MAX_TOKENS: int = 512
    # Stop taking work when the machine is busy with other things.
    AI_MIN_AVAILABLE_MEMORY_MB: int = 1024  # once the model is loaded
    AI_MAX_LOAD_PER_CPU: float = 1.5  # 1-minute load average divided by logical CPUs
    AI_MAX_RETRIES: int = 1  # extra attempts when Ollama cannot be reached; never after a timeout

    LOG_LEVEL: str = "INFO"

    @model_validator(mode="after")
    def _check(self) -> "AdapterSettings":
        ollama = urlparse(self.OLLAMA_BASE_URL)
        if ollama.scheme not in ("http", "https") or not ollama.hostname:
            raise ValueError("OLLAMA_BASE_URL must be an http(s) URL")
        if ollama.hostname not in LOCAL_HOSTS and not self.ALLOW_REMOTE_OLLAMA:
            raise ValueError("OLLAMA_BASE_URL must be on this machine (set ALLOW_REMOTE_OLLAMA=true to override)")
        cp = urlparse(self.AGENTMESH_CONTROL_PLANE_URL)
        if cp.scheme not in ("http", "https") or not cp.hostname:
            raise ValueError("AGENTMESH_CONTROL_PLANE_URL must be an http(s) URL")
        if cp.scheme == "http" and cp.hostname not in LOCAL_HOSTS and not self.ALLOW_INSECURE_CONTROL_PLANE:
            raise ValueError("AGENTMESH_CONTROL_PLANE_URL must use https (the inference token travels in headers)")
        if not NODE_ID_RE.fullmatch(self.AI_INFERENCE_NODE_ID):
            raise ValueError("AI_INFERENCE_NODE_ID must be letters, digits, '.', '_' or '-' (max 64)")
        if not 1 <= self.AI_MAX_CONCURRENT_REQUESTS <= 4:
            raise ValueError("AI_MAX_CONCURRENT_REQUESTS must be 1-4 on a single machine")
        if not 10 <= self.AI_REQUEST_TIMEOUT <= 3600:
            raise ValueError("AI_REQUEST_TIMEOUT must be 10-3600 seconds")
        if not 1024 <= self.AI_NUM_CTX <= 32768 or not 16 <= self.AI_MAX_TOKENS <= 4096:
            raise ValueError("AI_NUM_CTX must be 1024-32768 and AI_MAX_TOKENS 16-4096")
        return self

    @property
    def control_plane(self) -> str:
        return self.AGENTMESH_CONTROL_PLANE_URL.rstrip("/")

    @property
    def ollama(self) -> str:
        return self.OLLAMA_BASE_URL.rstrip("/")


def load_settings(**overrides) -> AdapterSettings:
    path = config_file()
    return AdapterSettings(_env_file=str(path) if path.exists() else None, **overrides)  # type: ignore[call-arg]
