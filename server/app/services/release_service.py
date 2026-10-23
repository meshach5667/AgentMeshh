"""Serves signed worker releases. The control plane never signs anything and cannot forge an update: workers
verify the manifest signature against the release key pinned in their own config."""

import json
import re
from pathlib import Path

from app.core.config import settings

WHEEL_RE = re.compile(r"^agentmesh_worker-\d+\.\d+\.\d+-py3-none-any\.whl$")


def release_dir() -> Path | None:
    return Path(settings.WORKER_RELEASE_DIR) if settings.WORKER_RELEASE_DIR else None


def latest() -> dict | None:
    base = release_dir()
    if base is None or not (base / "manifest.json").is_file() or not (base / "manifest.sig").is_file():
        return None
    return {
        "manifest": (base / "manifest.json").read_text(),
        "signature": (base / "manifest.sig").read_text().strip(),
    }


def latest_version() -> str | None:
    release = latest()
    if release is None:
        return None
    try:
        version = json.loads(release["manifest"]).get("version")
    except ValueError:
        return None
    return str(version) if version else None


def wheel_path(name: str) -> Path | None:
    base = release_dir()
    if base is None or not WHEEL_RE.fullmatch(name):
        return None
    path = (base / name).resolve()
    if path.parent != base.resolve() or not path.is_file():
        return None
    return path
