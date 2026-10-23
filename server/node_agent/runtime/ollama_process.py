"""Ollama backend for the installable agent: one dedicated ``ollama serve`` process per deployment.

Isolation from the provider's own setup: a random loopback port, a separate model directory under the
worker's data dir, and a minimal environment. The provider's existing Ollama service, port 11434, and
~/.ollama are never used. When systemd user scopes are available, each process runs in its own cgroup with
MemoryMax and CPUQuota; otherwise limits are advisory (scheduler reservations only) and that is reported.

This backend is not a security sandbox: the runtime runs as the provider's user.
"""

import asyncio
import os
import shutil
from pathlib import Path

from . import ollama_api
from .base import ProgressCallback, RuntimeCapabilities, WorkloadError, WorkloadHandle, WorkloadRuntime, WorkloadSpec
from .process_utils import CgroupProbe, base_env, free_port, own_process, spawn, terminate

_free_port = free_port  # kept for callers that imported the old private name


class OllamaProcessRuntime(WorkloadRuntime):
    name = "ollama"
    backend = "process"
    allowed_paths = ollama_api.ALLOWED_PATHS

    def __init__(self, data_dir: Path, binary: str = "ollama", cgroup_limits: bool = True):
        self.data_dir = data_dir
        self.models_dir = data_dir / "models"
        self.logs_dir = data_dir / "logs"
        self.binary = shutil.which(binary) or binary
        self.cgroups = CgroupProbe(cgroup_limits)
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def _cgroups_available(self) -> bool:
        return await self.cgroups.available()

    async def capabilities(self) -> RuntimeCapabilities:
        version, available, detail = "", False, ""
        if os.path.isfile(self.binary) and os.access(self.binary, os.X_OK):
            proc = await asyncio.create_subprocess_exec(
                self.binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            out, _ = await proc.communicate()
            version = next((tok for tok in out.decode(errors="ignore").split() if tok[:1].isdigit()), "")[:50]
            available = True
        else:
            detail = "ollama binary not found"
        cg = await self._cgroups_available()
        return RuntimeCapabilities(
            name="ollama",
            version=version,
            backend="process",
            available=available,
            gpu=False,
            limits_enforced=cg,
            detail=detail or ("cgroup limits via systemd user scope" if cg else "limits advisory"),
        )

    def _env(self, port: int, spec: WorkloadSpec) -> dict[str, str]:
        env = base_env(self.data_dir / "home", spec.gpu)
        env.update(
            {
                "OLLAMA_HOST": f"127.0.0.1:{port}",
                "OLLAMA_MODELS": str(self.models_dir),
                "OLLAMA_KEEP_ALIVE": "-1",
                "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_MAX_LOADED_MODELS": "1",
                "OLLAMA_NOHISTORY": "1",
            }
        )
        return env

    async def start(self, spec: WorkloadSpec) -> WorkloadHandle:
        for d in (self.models_dir, self.logs_dir, self.data_dir / "home"):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
        port = free_port()
        cgroup = await self._cgroups_available()
        proc = await spawn(
            [self.binary, "serve"],
            env=self._env(port, spec),
            log_path=self.logs_dir / f"{spec.deployment_id}.log",
            scope=f"agentmesh-wl-{spec.deployment_id[:8]}-{port}" if cgroup else None,
            ram_mb=spec.ram_mb,
            cpu_cores=spec.cpu_cores,
        )
        self._procs[spec.deployment_id] = proc
        handle = WorkloadHandle(
            deployment_id=spec.deployment_id,
            base_url=f"http://127.0.0.1:{port}",
            backend="process",
            ref={"pid": proc.pid, "port": port, "cgroup": cgroup, "runtime": self.name},
        )

        async def alive():
            return proc.returncode is None

        try:
            await ollama_api.wait_api(handle.base_url, timeout=60, is_alive=alive)
        except WorkloadError:
            await self.remove(handle)
            raise
        return handle

    async def prepare_model(self, handle: WorkloadHandle, spec: WorkloadSpec, progress: ProgressCallback) -> None:
        await ollama_api.pull(handle.base_url, spec.model_tag, progress)

    async def verify_ready(self, handle: WorkloadHandle, spec: WorkloadSpec) -> str | None:
        return await ollama_api.verify_ready(handle.base_url, spec.model_tag, spec.num_ctx)

    async def health(self, handle: WorkloadHandle, spec: WorkloadSpec) -> bool:
        return await self.is_alive(handle) and await ollama_api.health(handle.base_url, spec.model_tag)

    def _own_process(self, handle: WorkloadHandle):
        # Ollama receives its port through OLLAMA_HOST (environment), not its command line.
        return own_process(handle.ref.get("pid"), "ollama", handle.ref.get("port"))

    async def is_alive(self, handle: WorkloadHandle) -> bool:
        return self._own_process(handle) is not None

    async def remove(self, handle: WorkloadHandle) -> None:
        await terminate(self._own_process(handle), self._procs.pop(handle.deployment_id, None))
