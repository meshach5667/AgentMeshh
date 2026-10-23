"""vLLM backends (GPU only): a ``vllm serve`` process (installable agent) or a vllm/vllm-openai container
(Docker worker).

Differences from Ollama and llama.cpp:

* GPU required. Non-GPU deployments are refused rather than run slowly or not at all.
* vLLM downloads the full Hugging Face repository itself at the pinned commit. Integrity rests on the pinned
  revision (content-addressed by the Hub); there is no single-file SHA-256 as with GGUF.
* Only the OpenAI-compatible routes are exposed. Readiness: /health 200, then a real test generation.
* vLLM's usage telemetry is disabled.

STATUS: implemented and unit-tested with fakes only. It has not run on real GPU hardware (see
docs/IMPLEMENTATION_PLAN.md).
"""

import asyncio
import os
import shutil
import time
from pathlib import Path

import httpx

from .base import ProgressCallback, RuntimeCapabilities, WorkloadError, WorkloadHandle, WorkloadRuntime, WorkloadSpec
from .model_store import validate_source
from .ollama_docker import OllamaDockerRuntime
from .process_utils import CgroupProbe, base_env, free_port, own_process, spawn, terminate

LOAD_TIMEOUT_SECONDS = 1800  # includes downloading the weights
NO_TELEMETRY = {"VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}


def _check_spec(spec: WorkloadSpec) -> dict:
    if not spec.gpu:
        raise WorkloadError("UNSUPPORTED_RUNTIME", "vLLM deployments require a GPU")
    return validate_source(spec.source, needs_file=False)


def _serve_args(spec: WorkloadSpec, source: dict, host: str, port: int, gpu_fraction: float) -> list[str]:
    return [
        "--model",
        source["repo"],
        "--revision",
        source["revision"],
        "--host",
        host,
        "--port",
        str(port),
        "--served-model-name",
        spec.model_tag,
        "--max-model-len",
        str(spec.num_ctx),
        "--gpu-memory-utilization",
        f"{gpu_fraction:.2f}",
        "--disable-log-requests",
    ]


async def _wait_ready(base_url: str, alive, timeout: float = LOAD_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.monotonic() < deadline:
            if not await alive():
                raise WorkloadError("RUNTIME_START_FAILED", "vLLM exited while loading the model")
            try:
                if (await client.get(f"{base_url}/health")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
    raise WorkloadError("MODEL_PULL_STALLED", "vLLM did not finish loading the model in time", transient=True)


async def _test_generation(base_url: str, spec: WorkloadSpec, source: dict) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                json={
                    "model": spec.model_tag,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 2,
                },
            )
        except httpx.HTTPError as exc:
            raise WorkloadError("HEALTHCHECK_FAILED", f"Test generation failed: {type(exc).__name__}") from None
    if resp.status_code != 200 or not resp.json().get("choices"):
        raise WorkloadError("HEALTHCHECK_FAILED", f"Test generation returned HTTP {resp.status_code}")
    return f"hf:{source['revision']}"


def _gpu_fraction(spec: WorkloadSpec, total_vram_mb: int) -> float:
    """Limit vLLM to the VRAM AgentMesh reserved instead of its default 90% of the card."""
    if total_vram_mb <= 0 or spec.vram_mb <= 0:
        return 0.9
    return max(0.1, min(0.95, spec.vram_mb / total_vram_mb))


class VLLMProcessRuntime(WorkloadRuntime):
    name = "vllm"
    backend = "process"

    def __init__(self, data_dir: Path, binary: str = "vllm", cgroup_limits: bool = True, total_vram_mb: int = 0):
        self.data_dir = data_dir
        self.binary = shutil.which(binary) or binary
        self.cgroups = CgroupProbe(cgroup_limits)
        self.total_vram_mb = total_vram_mb
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def capabilities(self) -> RuntimeCapabilities:
        available = os.path.isfile(self.binary) and os.access(self.binary, os.X_OK) and self.total_vram_mb > 0
        detail = "" if available else ("no GPU detected" if self.total_vram_mb <= 0 else "vllm not installed")
        return RuntimeCapabilities(self.name, "", "process", available, True, await self.cgroups.available(), detail)

    async def start(self, spec: WorkloadSpec) -> WorkloadHandle:
        _check_spec(spec)
        port = free_port()
        return WorkloadHandle(
            spec.deployment_id, f"http://127.0.0.1:{port}", "process", {"port": port, "runtime": self.name}
        )

    async def prepare_model(self, handle: WorkloadHandle, spec: WorkloadSpec, progress: ProgressCallback) -> None:
        source = _check_spec(spec)
        port = handle.ref["port"]
        env = base_env(self.data_dir / "home", gpu=True)
        env.update(NO_TELEMETRY | {"HF_HOME": str(self.data_dir / "hf")})
        cgroup = await self.cgroups.available()
        await progress("Starting vLLM (downloads the model at the pinned revision)")
        proc = await spawn(
            [
                self.binary,
                "serve",
                *_serve_args(spec, source, "127.0.0.1", port, _gpu_fraction(spec, self.total_vram_mb)),
            ],
            env=env,
            log_path=self.data_dir / "logs" / f"{spec.deployment_id}.log",
            scope=f"agentmesh-wl-{spec.deployment_id[:8]}-{port}" if cgroup else None,
            ram_mb=spec.ram_mb,
            cpu_cores=spec.cpu_cores,
        )
        self._procs[spec.deployment_id] = proc
        handle.ref.update({"pid": proc.pid, "cgroup": cgroup})

        async def alive():
            return proc.returncode is None

        await _wait_ready(handle.base_url, alive)

    async def verify_ready(self, handle: WorkloadHandle, spec: WorkloadSpec) -> str | None:
        return await _test_generation(handle.base_url, spec, _check_spec(spec))

    async def health(self, handle: WorkloadHandle, spec: WorkloadSpec) -> bool:
        if not await self.is_alive(handle):
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                return (await client.get(f"{handle.base_url}/health")).status_code == 200
        except httpx.HTTPError:
            return False

    def _own_process(self, handle: WorkloadHandle):
        return own_process(handle.ref.get("pid"), "vllm", handle.ref.get("port"))

    async def is_alive(self, handle: WorkloadHandle) -> bool:
        return self._own_process(handle) is not None

    async def remove(self, handle: WorkloadHandle) -> None:
        await terminate(self._own_process(handle), self._procs.pop(handle.deployment_id, None))


class VLLMDockerRuntime(OllamaDockerRuntime):
    """vllm/vllm-openai container with the same hardening, labels, networks and egress handling as the Ollama
    container. The model is loaded at container start, so readiness is awaited in prepare_model."""

    name = "vllm"
    internal_port = 8000
    allowed_paths = WorkloadRuntime.allowed_paths

    def __init__(self, image: str, hf_cache_volume: str = "agentmesh-hf-cache", total_vram_mb: int = 0, **kwargs):
        super().__init__(image=image, **kwargs)
        self.hf_cache_volume = hf_cache_volume
        self.total_vram_mb = total_vram_mb

    async def capabilities(self) -> RuntimeCapabilities:
        caps = await super().capabilities()
        caps.name = self.name
        caps.gpu = True
        if not (self.allow_gpu and self.total_vram_mb > 0):
            caps.available, caps.detail = False, "vLLM needs a GPU and AGENTMESH_ALLOW_GPU=true"
        return caps

    def _container_config(self, spec: WorkloadSpec) -> dict:
        source = _check_spec(spec)
        return {
            "command": _serve_args(
                spec, source, "0.0.0.0", self.internal_port, _gpu_fraction(spec, self.total_vram_mb)
            ),
            "environment": NO_TELEMETRY | {"HF_HOME": "/cache/hf"},
            "volumes": {self.hf_cache_volume: {"bind": "/cache/hf", "mode": "rw"}},
            # vLLM writes compile caches under $HOME; keep the root filesystem writable but give it shared memory
            # for tensor-parallel workers instead of using the host IPC namespace.
            "read_only": False,
            "shm_size": "2g",
            "tmpfs": {"/tmp": "rw,nosuid,size=2g"},
        }

    async def start(self, spec: WorkloadSpec) -> WorkloadHandle:
        _check_spec(spec)
        if not self.allow_gpu:
            raise WorkloadError("UNSUPPORTED_RUNTIME", "GPU use is not allowed on this node")
        return await super().start(spec)

    async def _wait_started(self, base_url: str, alive) -> None:
        return None  # loading (and downloading) happens in prepare_model

    async def prepare_model(self, handle: WorkloadHandle, spec: WorkloadSpec, progress: ProgressCallback) -> None:
        await progress("vLLM is downloading and loading the model at the pinned revision")

        async def alive():
            return await self.is_alive(handle)

        try:
            await _wait_ready(handle.base_url, alive)
        finally:
            if self.egress_restricted:
                await self._cut_egress(handle)

    async def verify_ready(self, handle: WorkloadHandle, spec: WorkloadSpec) -> str | None:
        return await _test_generation(handle.base_url, spec, _check_spec(spec))

    async def health(self, handle: WorkloadHandle, spec: WorkloadSpec) -> bool:
        if not await self.is_alive(handle):
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                return (await client.get(f"{handle.base_url}/health")).status_code == 200
        except httpx.HTTPError:
            return False
