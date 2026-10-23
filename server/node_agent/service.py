"""Run the worker as a per-user background service: systemd user unit (Linux) or launchd agent (macOS).

No administrator rights are needed. Units are written under the user's own config directories, and
``uninstall`` removes exactly what ``install`` wrote.
"""

import os
import platform
import plistlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_NAME = "agentmesh-worker"
LAUNCHD_PREFIX = "io.agentmesh."


@dataclass
class ServiceFiles:
    path: Path
    content: bytes


def _check_name(name: str) -> str:
    if not name or not all(c.isalnum() or c in "-_." for c in name) or len(name) > 64:
        raise ValueError("service name may only contain letters, digits, '-', '_' and '.'")
    return name


def systemd_unit_path(name: str) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "systemd" / "user" / f"{name}.service"


def launchd_plist_path(name: str) -> Path:
    return Path(os.path.expanduser("~/Library/LaunchAgents")) / f"{LAUNCHD_PREFIX}{name}.plist"


def render_systemd(name: str, executable: str, config_file: str) -> ServiceFiles:
    unit = f"""# Installed by agentmesh-worker. Remove with: agentmesh-worker service uninstall --name {name}
[Unit]
Description=AgentMesh worker ({name})
Documentation=https://github.com/meshach5667/AgentMeshh/blob/main/docs/WORKER.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=AGENTMESH_CONFIG_FILE={config_file}
ExecStart={executable} run
Restart=on-failure
RestartSec=10
# The worker stops its runtimes itself on SIGTERM; give it time to report and clean up.
TimeoutStopSec=60
# Hardening that does not need root. Runtimes live in their own systemd scopes with their own limits.
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=default.target
"""
    return ServiceFiles(systemd_unit_path(name), unit.encode())


def render_launchd(name: str, executable: str, config_file: str, log_dir: str) -> ServiceFiles:
    plist = {
        "Label": f"{LAUNCHD_PREFIX}{name}",
        "ProgramArguments": [executable, "run"],
        "EnvironmentVariables": {"AGENTMESH_CONFIG_FILE": config_file},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},  # restart after crashes, not after a clean stop
        "ThrottleInterval": 10,
        "ExitTimeOut": 60,
        "StandardOutPath": str(Path(log_dir) / f"{name}.log"),
        "StandardErrorPath": str(Path(log_dir) / f"{name}.log"),
        "ProcessType": "Background",
    }
    return ServiceFiles(launchd_plist_path(name), plistlib.dumps(plist))


def _run(argv: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=check, timeout=60)


def install(name: str, executable: str, config_file: str, log_dir: str, linger: bool = False) -> str:
    name = _check_name(name)
    system = platform.system()
    if system == "Linux":
        if not shutil.which("systemctl"):
            raise RuntimeError("systemd is not available; run 'agentmesh-worker run' under your own supervisor")
        files = render_systemd(name, executable, config_file)
        files.path.parent.mkdir(parents=True, exist_ok=True)
        files.path.write_bytes(files.content)
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", f"{name}.service"])
        note = ""
        if linger:
            result = _run(["loginctl", "enable-linger", os.environ.get("USER", "")], check=False)
            note = (
                " Lingering enabled (runs without an active login)."
                if result.returncode == 0
                else (f" Could not enable lingering: {result.stderr.strip()}")
            )
        return f"Installed and started systemd user service '{name}' ({files.path}).{note}"
    if system == "Darwin":
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        files = render_launchd(name, executable, config_file, log_dir)
        files.path.parent.mkdir(parents=True, exist_ok=True)
        files.path.write_bytes(files.content)
        uid = os.getuid()
        _run(["launchctl", "bootout", f"gui/{uid}", str(files.path)], check=False)
        _run(["launchctl", "bootstrap", f"gui/{uid}", str(files.path)])
        return f"Installed and started launchd agent '{LAUNCHD_PREFIX}{name}' ({files.path})."
    raise RuntimeError(f"{system} is not supported; use the Docker worker")


def uninstall(name: str) -> str:
    name = _check_name(name)
    system = platform.system()
    if system == "Linux":
        path = systemd_unit_path(name)
        if shutil.which("systemctl"):
            _run(["systemctl", "--user", "disable", "--now", f"{name}.service"], check=False)
        existed = path.exists()
        path.unlink(missing_ok=True)
        if shutil.which("systemctl"):
            _run(["systemctl", "--user", "daemon-reload"], check=False)
            _run(["systemctl", "--user", "reset-failed", f"{name}.service"], check=False)
        return f"Removed systemd user service '{name}'." if existed else f"No service named '{name}' was installed."
    if system == "Darwin":
        path = launchd_plist_path(name)
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], check=False)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return f"Removed launchd agent '{name}'." if existed else f"No service named '{name}' was installed."
    raise RuntimeError(f"{system} is not supported")


def status(name: str) -> str:
    name = _check_name(name)
    if platform.system() == "Linux":
        result = _run(["systemctl", "--user", "is-active", f"{name}.service"], check=False)
        return result.stdout.strip() or result.stderr.strip()
    if platform.system() == "Darwin":
        result = _run(["launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_PREFIX}{name}"], check=False)
        return "active" if result.returncode == 0 else "inactive"
    return "unsupported"
