"""Signed worker updates.

The operator signs a release manifest with an offline Ed25519 key (scripts/sign_worker_release.py). Workers
trust only the public key pinned in their config (AGENTMESH_UPDATE_PUBLIC_KEY, set by the installer), so a
compromised control plane cannot push code: it can only serve manifests that the release key signed.

Manifest (JSON, signed byte-for-byte):
    {"version": "0.3.1", "wheel": "agentmesh_worker-0.3.1-py3-none-any.whl", "sha256": "<hex>", "size": 12345}

Steps: fetch manifest + signature, verify the signature, refuse anything that is not newer, download the
wheel, check size and SHA-256, install it into this worker's own Python environment, confirm the new version
imports and reports the expected version, and roll back to the previously installed wheel if not.
"""

import asyncio
import base64
import hashlib
import json
import logging
import re
import shutil
import sys
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .config import WORKER_VERSION, WorkerSettings
from .protocol import ControlPlaneClient
from .state import WorkerState

logger = logging.getLogger(__name__)

MAX_WHEEL_BYTES = 50 * 1024 * 1024
WHEEL_RE = re.compile(r"^agentmesh_worker-(\d+\.\d+\.\d+)-py3-none-any\.whl$")


class UpdateError(Exception):
    pass


def parse_version(text: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        raise UpdateError(f"invalid version {text!r}")
    return int(m[1]), int(m[2]), int(m[3])


def verify_manifest(manifest_bytes: bytes, signature_b64: str, public_key_b64: str) -> dict:
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        key.verify(base64.b64decode(signature_b64, validate=True), manifest_bytes)
    except (ValueError, InvalidSignature) as exc:
        raise UpdateError("release signature is invalid") from exc
    manifest = json.loads(manifest_bytes)
    m = WHEEL_RE.fullmatch(str(manifest.get("wheel", "")))
    if not m or m[1] != manifest.get("version"):
        raise UpdateError("manifest wheel name does not match its version")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("sha256", ""))):
        raise UpdateError("manifest has no valid sha256")
    parse_version(manifest["version"])
    return manifest


async def _pip(*args: str) -> int:
    # -I (isolated): ignore the current directory and PYTHON* variables so pip and the version probe act on this
    # worker's own environment, never on a stray node_agent package next to wherever `update` was run.
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-m",
        "pip",
        "--disable-pip-version-check",
        "--quiet",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode:
        logger.error("pip %s failed: %s", " ".join(args), out.decode(errors="ignore")[-500:])
    return proc.returncode or 0


async def _installed_version() -> str | None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-m",
        "node_agent",
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    text = out.decode(errors="ignore").strip()
    return text.rsplit(" ", 1)[-1] if proc.returncode == 0 and text else None


class Updater:
    def __init__(self, settings: WorkerSettings, client: ControlPlaneClient, install=_pip, probe=_installed_version):
        self.settings = settings
        self.client = client
        self.state = WorkerState(settings.data_path)
        self.releases = settings.data_path / "releases"
        self._install = install
        self._probe = probe

    async def latest(self) -> dict | None:
        if not self.settings.UPDATE_PUBLIC_KEY:
            raise UpdateError("updates are disabled: no trusted release key (AGENTMESH_UPDATE_PUBLIC_KEY)")
        resp = await self.client._client.get(f"{self.client.api}/releases/latest", headers=self.client.headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
        return verify_manifest(body["manifest"].encode(), body["signature"], self.settings.UPDATE_PUBLIC_KEY)

    async def download(self, manifest: dict) -> Path:
        self.releases.mkdir(parents=True, exist_ok=True)
        target = self.releases / manifest["wheel"]
        digest = hashlib.sha256()
        size = 0
        tmp = target.with_suffix(".part")
        async with self.client._client.stream(
            "GET", f"{self.client.api}/releases/files/{manifest['wheel']}", headers=self.client.headers
        ) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_WHEEL_BYTES:
                        raise UpdateError("release file is too large")
                    digest.update(chunk)
                    fh.write(chunk)
        if digest.hexdigest() != manifest["sha256"]:
            tmp.unlink(missing_ok=True)
            raise UpdateError("downloaded wheel does not match the signed sha256")
        tmp.replace(target)
        return target

    async def apply(self, check_only: bool = False) -> str:
        manifest = await self.latest()
        if manifest is None:
            return "No release published."
        current = parse_version(WORKER_VERSION)
        offered = parse_version(manifest["version"])
        if offered <= current:
            return f"Up to date ({WORKER_VERSION}; latest signed release {manifest['version']})."
        if check_only:
            return f"Update available: {WORKER_VERSION} -> {manifest['version']} (signature verified)."
        wheel = await self.download(manifest)
        previous = self.releases / f"agentmesh_worker-{WORKER_VERSION}-py3-none-any.whl"
        if await self._install("install", "--force-reinstall", "--no-deps", str(wheel)) != 0:
            raise UpdateError("installing the update failed; nothing changed")
        # Dependencies may have changed between releases; install them without touching our package.
        await self._install("install", str(wheel))
        if await self._probe() != manifest["version"]:
            if previous.exists():
                await self._install("install", "--force-reinstall", "--no-deps", str(previous))
                raise UpdateError(f"new version did not start; rolled back to {WORKER_VERSION}")
            raise UpdateError("new version did not start and no previous wheel is cached for rollback")
        return f"Updated {WORKER_VERSION} -> {manifest['version']}. Restart the worker to use it."


async def run(settings: WorkerSettings, check_only: bool = False) -> int:
    creds = WorkerState(settings.data_path).load_credentials()
    if not creds:
        print("Not enrolled.")
        return 1
    client = ControlPlaneClient(settings.CONTROL_PLANE_URL, creds["node_id"], creds["node_credential"])
    try:
        print(await Updater(settings, client).apply(check_only=check_only))
        return 0
    except (UpdateError, httpx.HTTPError) as exc:
        print(f"Update failed: {exc}")
        return 1
    finally:
        await client.close()


def cache_current_wheel(settings: WorkerSettings, wheel: Path) -> None:
    """Keep the installed wheel so a failed update can roll back to it (called by the installer)."""
    releases = settings.data_path / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wheel, releases / wheel.name)
