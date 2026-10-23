"""Worker state persisted under DATA_DIR. Credentials are written with 0600 permissions."""

import json
import os
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any


def _atomic_write(path: Path, data: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read(path: Path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


class WorkerState:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.credentials_path = data_dir / "credentials.json"
        self.workloads_path = data_dir / "workloads.json"
        self.commands_path = data_dir / "processed_commands.json"
        self.workloads: dict[str, dict] = _read(self.workloads_path, {})
        self._processed: deque[str] = deque(_read(self.commands_path, []), maxlen=1000)

    # credentials ------------------------------------------------------------------------------------
    def load_credentials(self) -> dict | None:
        creds = _read(self.credentials_path, None)
        if creds and creds.get("node_id") and creds.get("node_credential"):
            return creds
        return None

    def save_credentials(self, node_id: str, credential: str, control_plane_url: str) -> None:
        _atomic_write(
            self.credentials_path,
            {"node_id": node_id, "node_credential": credential, "control_plane_url": control_plane_url},
        )

    def delete_credentials(self) -> None:
        self.credentials_path.unlink(missing_ok=True)

    # workloads --------------------------------------------------------------------------------------
    def put_workload(self, deployment_id: str, record: dict) -> None:
        self.workloads[deployment_id] = record
        _atomic_write(self.workloads_path, self.workloads)

    def drop_workload(self, deployment_id: str) -> None:
        if self.workloads.pop(deployment_id, None) is not None:
            _atomic_write(self.workloads_path, self.workloads)

    # local control (pause / drain / resume from the CLI) ------------------------------------------------
    @property
    def control_path(self) -> Path:
        return self.dir / "control.json"

    def control(self) -> dict:
        data = _read(self.control_path, {})
        return {"paused": bool(data.get("paused")), "draining": bool(data.get("draining"))}

    def set_control(self, *, paused: bool, draining: bool) -> None:
        _atomic_write(self.control_path, {"paused": paused, "draining": draining, "updated": time.time()}, mode=0o644)

    # liveness (used by the container health check) --------------------------------------------------
    def record_heartbeat(self) -> None:
        _atomic_write(self.dir / "health.json", {"last_heartbeat": time.time()}, mode=0o644)

    def seconds_since_heartbeat(self) -> float | None:
        data = _read(self.dir / "health.json", None)
        return time.time() - float(data["last_heartbeat"]) if data else None

    # command idempotency ----------------------------------------------------------------------------
    def seen(self, command_id: str) -> bool:
        return command_id in self._processed

    def mark_processed(self, command_id: str) -> None:
        if command_id not in self._processed:
            self._processed.append(command_id)
            _atomic_write(self.commands_path, list(self._processed))
