"""llama.cpp backend for the installable agent: one ``llama-server`` process per deployment, serving a single
verified GGUF file over its OpenAI-compatible API.

Differences from Ollama that callers should know:

* Model files come from Hugging Face (pinned commit + SHA-256), not a model registry, and are verified before
  the server starts. ``start`` only allocates the instance; ``prepare_model`` downloads and launches.
* Only the OpenAI-compatible routes (/v1/chat/completions, /v1/completions) are exposed; Ollama-native /api/*
  routes are not available for llama.cpp deployments.
* CPU by default. GPU offload (-ngl) is used only for GPU deployments on a llama-server build that supports it.

Same isolation as the Ollama process backend: loopback port, own process group, minimal environment, and a
systemd user scope with hard memory/CPU limits when available. Not a security sandbox.
"""

import asyncio
import os
import shutil
import time
from pathlib import Path

import httpx

from .base import ProgressCallback, RuntimeCapabilities, WorkloadError, WorkloadHandle, WorkloadRuntime, WorkloadSpec
from .model_store import DEFAULT_ALLOWED_HOSTS, ModelStore, validate_source
from .process_utils import CgroupProbe, base_env, free_port, own_process, spawn, terminate

READY_TIMEOUT_SECONDS = 300


class LlamaCppProcessRuntime(WorkloadRuntime):
    name = "llamacpp"
    backend = "process"

    def __init__(
        self,
        data_dir: Path,
        binary: str = "llama-server",
        cgroup_limits: bool = True,
        allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
        store: ModelStore | None = None,
    ):
        self.data_dir = data_dir
        self.logs_dir = data_dir / "logs"
        self.binary = shutil.which(binary) or binary
        self.cgroups = CgroupProbe(cgroup_limits)
        self.store = store or ModelStore(data_dir / "gguf", allowed_hosts)
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def capabilities(self) -> RuntimeCapabilities:
        version, available, detail = "", False, ""
        if os.path.isfile(self.binary) and os.access(self.binary, os.X_OK):
            proc = await asyncio.create_subprocess_exec(
                self.binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            out, _ = await proc.communicate()
            text = out.decode(errors="ignore")
            for line in text.splitlines():
                if line.lower().startswith("version"):
                    version = line.split(":", 1)[-1].strip().split()[0][:50]
            available = proc.returncode == 0
            if not available:
                detail = "llama-server did not run"
        else:
            detail = "llama-server binary not found"
        cg = await self.cgroups.available()
        return RuntimeCapabilities(
            name=self.name,
            version=version,
            backend="process",
            available=available,
            gpu=False,
            limits_enforced=cg,
            detail=detail or ("cgroup limits via systemd user scope" if cg else "limits advisory"),
        )

    async def start(self, spec: WorkloadSpec) -> WorkloadHandle:
        validate_source(spec.source, needs_file=True)
        port = free_port()
        return WorkloadHandle(
            deployment_id=spec.deployment_id,
            base_url=f"http://127.0.0.1:{port}",
            backend="process",
            ref={"port": port, "runtime": self.name},
        )

    def _argv(self, model_path: Path, port: int, spec: WorkloadSpec) -> list[str]:
        argv = [
            self.binary,
            "-m",
            str(model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "-c",
            str(spec.num_ctx),
            "-t",
            str(spec.cpu_cores),
            "--parallel",
            "1",
            "--alias",
            spec.model_tag,
            "-ngl",
            "999" if spec.gpu else "0",
        ]
        return argv

    async def prepare_model(self, handle: WorkloadHandle, spec: WorkloadSpec, progress: ProgressCallback) -> None:
        source = validate_source(spec.source, needs_file=True)
        free_mb = shutil.disk_usage(self.data_dir if self.data_dir.exists() else self.data_dir.parent).free // 2**20
        needed_mb = source.get("size", 0) // 2**20
        if not self.store.is_cached(source) and free_mb < needed_mb:
            raise WorkloadError("INSUFFICIENT_DISK", f"{needed_mb} MB needed for the model, {free_mb} MB free")
        model_path = await self.store.fetch_gguf(source, progress)
        await progress("Model verified (SHA-256); starting llama-server")

        port = handle.ref["port"]
        cgroup = await self.cgroups.available()
        self.logs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        proc = await spawn(
            self._argv(model_path, port, spec),
            env=base_env(self.data_dir / "home", spec.gpu),
            log_path=self.logs_dir / f"{spec.deployment_id}.log",
            scope=f"agentmesh-wl-{spec.deployment_id[:8]}-{port}" if cgroup else None,
            ram_mb=spec.ram_mb,
            cpu_cores=spec.cpu_cores,
        )
        self._procs[spec.deployment_id] = proc
        handle.ref.update({"pid": proc.pid, "cgroup": cgroup, "model_path": str(model_path)})
        await self._wait_loaded(handle, proc)

    async def _wait_loaded(self, handle: WorkloadHandle, proc: asyncio.subprocess.Process) -> None:
        """llama-server answers /health with 503 while loading and 200 once the model is in memory."""
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.monotonic() < deadline:
                if proc.returncode is not None:
                    raise WorkloadError("RUNTIME_START_FAILED", "llama-server exited while loading the model")
                try:
                    if (await client.get(f"{handle.base_url}/health")).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        raise WorkloadError("RUNTIME_START_FAILED", "llama-server did not finish loading the model in time")

    async def verify_ready(self, handle: WorkloadHandle, spec: WorkloadSpec) -> str | None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                resp = await client.post(
                    f"{handle.base_url}/v1/chat/completions",
                    json={
                        "model": spec.model_tag,
                        "messages": [{"role": "user", "content": "Reply with OK."}],
                        "max_tokens": 2,
                        "stream": False,
                    },
                )
            except httpx.HTTPError as exc:
                raise WorkloadError("HEALTHCHECK_FAILED", f"Test generation failed: {type(exc).__name__}") from None
        if resp.status_code != 200 or not resp.json().get("choices"):
            raise WorkloadError("HEALTHCHECK_FAILED", f"Test generation returned HTTP {resp.status_code}")
        return f"sha256:{spec.source['sha256']}" if spec.source else None

    async def health(self, handle: WorkloadHandle, spec: WorkloadSpec) -> bool:
        if not await self.is_alive(handle):
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                return (await client.get(f"{handle.base_url}/health")).status_code == 200
        except httpx.HTTPError:
            return False

    def _own_process(self, handle: WorkloadHandle):
        return own_process(handle.ref.get("pid"), "llama-server", handle.ref.get("port"))

    async def is_alive(self, handle: WorkloadHandle) -> bool:
        return self._own_process(handle) is not None

    async def remove(self, handle: WorkloadHandle) -> None:
        await terminate(self._own_process(handle), self._procs.pop(handle.deployment_id, None))
