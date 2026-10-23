"""Launching and supervising runtime processes for the installable agent (shared by all process runtimes).

Each runtime instance runs as the provider's user on a random loopback port, in its own process group, and -
when systemd user scopes are available - in its own cgroup with MemoryMax, MemorySwapMax=0 and CPUQuota.
Only a minimal environment is passed. Processes are identified by PID *and* command line, so a reused PID is
never mistaken for one of ours.
"""

import asyncio
import contextlib
import os
import shutil
import signal
import socket
from pathlib import Path

import psutil

from .base import WorkloadError


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class CgroupProbe:
    """Detects (once) whether `systemd-run --user --scope` works on this machine."""

    def __init__(self, wanted: bool):
        self.wanted = wanted
        self._available: bool | None = None

    async def available(self) -> bool:
        if self._available is None:
            self._available = False
            if self.wanted and shutil.which("systemd-run"):
                proc = await asyncio.create_subprocess_exec(
                    "systemd-run",
                    "--user",
                    "--scope",
                    "--quiet",
                    "-p",
                    "MemoryMax=64M",
                    "true",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                self._available = (await proc.wait()) == 0
        return self._available


def base_env(home: Path, gpu: bool) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    # systemd-run needs these to reach the user service manager; nothing else from the provider's env leaks.
    for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if key in os.environ:
            env[key] = os.environ[key]
    if not gpu:
        env.update({"CUDA_VISIBLE_DEVICES": "-1", "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1"})
    return env


async def spawn(
    argv: list[str], *, env: dict[str, str], log_path: Path, scope: str | None, ram_mb: int, cpu_cores: int
) -> asyncio.subprocess.Process:
    """Start ``argv`` in a new session, optionally wrapped in a limited systemd user scope."""
    if scope:
        argv = [
            "systemd-run",
            "--user",
            "--scope",
            "--quiet",
            f"--unit={scope}",
            "-p",
            f"MemoryMax={ram_mb}M",
            "-p",
            "MemorySwapMax=0",
            "-p",
            f"CPUQuota={cpu_cores * 100}%",
            "--",
            *argv,
        ]
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = open(log_path, "ab")  # noqa: SIM115
    try:
        return await asyncio.create_subprocess_exec(
            *argv, env=env, stdout=log, stderr=log, stdin=asyncio.subprocess.DEVNULL, start_new_session=True
        )
    except OSError as exc:
        raise WorkloadError("RUNTIME_START_FAILED", f"Could not start {Path(argv[0]).name}: {exc.strerror}") from None
    finally:
        log.close()


def own_process(pid: int | None, marker: str, port: int | None) -> psutil.Process | None:
    """Return the process only if it is still the runtime we started: same PID, a command line containing
    ``marker`` and (when known) the port we assigned. Guards against PID reuse."""
    if not pid:
        return None
    try:
        p = psutil.Process(pid)
        cmd = " ".join(p.cmdline())
        if marker not in cmd:
            return None
        if port is not None and str(port) not in cmd:
            with contextlib.suppress(psutil.Error):
                if not any(str(port) in v for v in p.environ().values()):
                    return None
        return p
    except psutil.Error:
        return None


async def terminate(p: psutil.Process | None, proc: asyncio.subprocess.Process | None) -> None:
    """SIGTERM the process group, wait, then SIGKILL. Reaps through asyncio when we own the Process object."""
    if p is None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(p.pid, signal.SIGTERM)
    if await _wait_gone(p, proc, 15):
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(p.pid, signal.SIGKILL)
    await _wait_gone(p, proc, 5)


async def _wait_gone(p: psutil.Process, proc, timeout: float) -> bool:
    if proc is not None:
        try:
            await asyncio.wait_for(proc.wait(), timeout)
            return True
        except TimeoutError:
            return False
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
            return True
        await asyncio.sleep(0.2)
    return False
