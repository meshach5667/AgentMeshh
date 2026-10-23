"""`agentmesh-worker doctor`: checks a machine's setup and says how to fix what is wrong.

Read-only: it never changes the provider's system. It does not start runtimes unless --deep is given, and
even then only a throwaway Ollama process on a random loopback port with a scratch model directory.
"""

import asyncio
import os
import platform
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
import psutil

from . import schedule as availability_schedule
from .config import WorkerSettings, config_file
from .hardware.discovery import default_allocation, hardware_report
from .protocol import ControlPlaneClient, CredentialRevoked, ProtocolError
from .state import WorkerState

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


async def _control_plane(settings: WorkerSettings, state: WorkerState) -> list[Check]:
    checks = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.CONTROL_PLANE_URL}/health")
        if resp.status_code == 200:
            checks.append(Check("Control plane reachable", OK, settings.CONTROL_PLANE_URL))
        else:
            checks.append(Check("Control plane reachable", FAIL, f"HTTP {resp.status_code}", "Check the URL"))
            return checks
    except httpx.HTTPError as exc:
        checks.append(
            Check(
                "Control plane reachable",
                FAIL,
                f"{settings.CONTROL_PLANE_URL}: {type(exc).__name__}",
                "Check AGENTMESH_CONTROL_PLANE_URL, your network, and any proxy or firewall",
            )
        )
        return checks

    creds = state.load_credentials()
    if not creds:
        checks.append(Check("Enrolled", FAIL, "No credentials", "Run: agentmesh-worker enroll --token <token>"))
        return checks
    client = ControlPlaneClient(settings.CONTROL_PLANE_URL, creds["node_id"], creds["node_credential"])
    try:
        me = await client.whoami()
        detail = f"node {me['node_id']} ({me['status']})"
        if not me.get("accepting_workloads"):
            checks.append(Check("Enrolled", WARN, detail + ", paused in the dashboard", "Resume it in the dashboard"))
        else:
            checks.append(Check("Enrolled", OK, detail))
    except CredentialRevoked:
        checks.append(
            Check(
                "Enrolled",
                FAIL,
                "Credential rejected (node revoked or deleted)",
                "Run: agentmesh-worker uninstall, then enroll again with a new token",
            )
        )
    except ProtocolError as exc:
        checks.append(Check("Enrolled", WARN, f"Could not verify: {exc}"))
    finally:
        await client.close()
    return checks


async def _deep_ollama(binary: str) -> Check:
    """Start a throwaway Ollama on a random port with a scratch model dir, then stop it."""
    from .runtime.ollama_process import _free_port

    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="agentmesh-doctor-") as tmp:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": tmp,
            "OLLAMA_HOST": f"127.0.0.1:{port}",
            "OLLAMA_MODELS": tmp,
        }
        proc = await asyncio.create_subprocess_exec(
            binary,
            "serve",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                for _ in range(40):
                    try:
                        if (await client.get(f"http://127.0.0.1:{port}/api/version")).status_code == 200:
                            return Check("Ollama can start an isolated instance", OK, f"port {port}, scratch model dir")
                    except httpx.HTTPError:
                        await asyncio.sleep(0.25)
            return Check(
                "Ollama can start an isolated instance",
                FAIL,
                "No answer within 10 s",
                "Reinstall Ollama from https://ollama.com/download",
            )
        finally:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 10)
            except TimeoutError:
                proc.kill()


async def _runtime(settings: WorkerSettings, deep: bool) -> list[Check]:
    checks = []
    if settings.RUNTIME_BACKEND == "process":
        binary = shutil.which(settings.OLLAMA_BINARY) or (
            settings.OLLAMA_BINARY if os.path.isfile(settings.OLLAMA_BINARY) else None
        )
        if not binary:
            checks.append(
                Check(
                    "Ollama installed",
                    FAIL,
                    f"'{settings.OLLAMA_BINARY}' not found",
                    "Install Ollama from https://ollama.com/download (AgentMesh never installs or changes it)",
                )
            )
            return checks
        proc = await asyncio.create_subprocess_exec(
            binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await proc.communicate()
        version = next((t for t in out.decode(errors="ignore").split() if t[:1].isdigit()), "unknown")
        checks.append(Check("Ollama installed", OK, f"{binary} {version}"))
        from .runtime.ollama_process import OllamaProcessRuntime

        rt = OllamaProcessRuntime(settings.data_path, binary, settings.PROCESS_CGROUP_LIMITS)
        if await rt._cgroups_available():
            checks.append(Check("Resource limits enforced", OK, "systemd user scopes (MemoryMax, CPUQuota)"))
        else:
            checks.append(
                Check(
                    "Resource limits enforced",
                    WARN,
                    "No systemd user scopes: limits are advisory",
                    "On Linux, run under a systemd user session; on macOS limits are advisory",
                )
            )
        with socket.socket() as s:
            own = s.connect_ex(("127.0.0.1", 11434)) == 0
        if own:
            checks.append(Check("Your own Ollama", INFO, "Running on port 11434; AgentMesh does not use or modify it"))
        if deep:
            checks.append(await _deep_ollama(binary))
    else:
        try:
            import docker

            client = docker.DockerClient(base_url=settings.DOCKER_HOST) if settings.DOCKER_HOST else docker.from_env()
            client.ping()
            checks.append(Check("Docker reachable", OK, client.version().get("Version", "")))
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "Permission denied" in text or "permission denied" in text:
                checks.append(
                    Check(
                        "Docker reachable",
                        FAIL,
                        "Permission denied on the Docker socket",
                        "sudo usermod -aG docker $USER, then log out and in (or use rootless Docker)",
                    )
                )
            else:
                checks.append(
                    Check(
                        "Docker reachable",
                        FAIL,
                        type(exc).__name__,
                        "Start Docker Engine, or set AGENTMESH_DOCKER_HOST",
                    )
                )
    return checks


def _resources(settings: WorkerSettings) -> list[Check]:
    hw = hardware_report(settings.DATA_DIR)
    alloc = default_allocation(hw, settings)
    checks = [
        Check(
            "Resources offered",
            INFO,
            f"{alloc['cpu_cores']} CPU cores, {alloc['ram_mb']} MB RAM, "
            f"{alloc['disk_mb']} MB disk, {alloc['vram_mb']} MB VRAM "
            f"(of {hw['cpu_cores']} cores, {hw['ram_mb']} MB RAM)",
        )
    ]
    if alloc["disk_mb"] < 1024:
        checks.append(
            Check(
                "Disk for models",
                FAIL,
                f"Only {alloc['disk_mb']} MB offered/free",
                "Free disk space or raise AGENTMESH_MAX_DISK_MB",
            )
        )
    available = psutil.virtual_memory().available // (1024 * 1024)
    if available < alloc["ram_mb"]:
        checks.append(
            Check(
                "Memory headroom",
                WARN,
                f"{available} MB free now but {alloc['ram_mb']} MB offered",
                "Lower AGENTMESH_MAX_RAM_MB, or deployments may fail with INSUFFICIENT_MEMORY",
            )
        )
    gpus = hw["gpus"]
    checks.append(
        Check(
            "GPUs",
            INFO,
            ", ".join(f"{g['vendor']} {g['model']} ({g['vram_mb']} MB)" for g in gpus)
            if gpus
            else "None detected" + ("" if not settings.ALLOW_GPU else "; ALLOW_GPU has no effect"),
        )
    )
    return checks


def _schedule(settings: WorkerSettings, state: WorkerState) -> list[Check]:
    windows = availability_schedule.parse(settings.AVAILABILITY_SCHEDULE)
    now = datetime.now()
    control = state.control()
    if control["draining"] or control["paused"]:
        return [
            Check(
                "Availability",
                WARN,
                "Draining" if control["draining"] else "Paused locally",
                "Run: agentmesh-worker resume",
            )
        ]
    if not windows:
        return [Check("Availability", OK, "Always (no schedule)")]
    nxt = availability_schedule.next_change(windows, now)
    on = availability_schedule.is_available(windows, now)
    detail = f"{'Available' if on else 'Outside schedule'} now; changes at {nxt:%a %H:%M}" if nxt else ""
    return [Check("Availability", OK if on else INFO, f"{settings.AVAILABILITY_SCHEDULE} - {detail}")]


def _platform() -> list[Check]:
    checks = []
    system = platform.system()
    if system not in ("Linux", "Darwin"):
        checks.append(
            Check("Platform", FAIL, f"{system} is not supported yet", "Use Linux or macOS, or the Docker worker")
        )
    else:
        checks.append(Check("Platform", OK, f"{system} {platform.machine()}"))
    if sys.version_info < (3, 11):  # noqa: UP036  (runtime check for providers on older Pythons)
        checks.append(Check("Python", FAIL, platform.python_version(), "Python 3.11 or newer is required"))
    else:
        checks.append(Check("Python", OK, platform.python_version()))
    return checks


async def run(settings: WorkerSettings | None, deep: bool = False, settings_error: str | None = None) -> list[Check]:
    checks = _platform()
    path = config_file()
    checks.append(
        Check(
            "Config file",
            OK if path.is_file() else INFO,
            str(path) if path.is_file() else f"{path} not found (using environment and defaults)",
        )
    )
    if settings is None:
        checks.append(Check("Configuration valid", FAIL, settings_error or "invalid", "Fix the config file"))
        return checks
    state = WorkerState(settings.data_path)
    try:
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True, mode=0o700)
        writable = os.access(settings.DATA_DIR, os.W_OK)
    except OSError:
        writable = False
    checks.append(
        Check(
            "Data directory writable",
            OK if writable else FAIL,
            settings.DATA_DIR,
            "" if writable else "Fix permissions or set AGENTMESH_DATA_DIR",
        )
    )
    checks += await _control_plane(settings, state)
    checks += await _runtime(settings, deep)
    checks += _resources(settings)
    checks += _schedule(settings, state)
    return checks


def render(checks: list[Check]) -> str:
    marks = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]", INFO: "[INFO]"}
    lines = []
    for c in checks:
        lines.append(f"{marks[c.status]} {c.name}: {c.detail}")
        if c.fix and c.status in (WARN, FAIL):
            lines.append(f"       fix: {c.fix}")
    return "\n".join(lines)
