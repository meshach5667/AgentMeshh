"""Build the agentmesh-worker wheel from server/node_agent, with no network access and no build backend.

    python scripts/build_worker_wheel.py            # writes dist/agentmesh_worker-<version>-py3-none-any.whl

The wheel contains only the worker package. Its dependencies come from requirements-worker.txt.
"""

import base64
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "node_agent"
DIST_NAME = "agentmesh_worker"


def _version() -> str:
    text = (PKG / "config.py").read_text()
    return re.search(r'WORKER_VERSION = "([^"]+)"', text).group(1)  # type: ignore[union-attr]


def _requirements() -> list[str]:
    lines = (ROOT / "requirements-worker.txt").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(data)}"


def build(out_dir: Path, version: str | None = None) -> Path:
    """Build the wheel. ``version`` overrides WORKER_VERSION (used to produce test releases)."""
    version = version or _version()
    dist_info = f"{DIST_NAME}-{version}.dist-info"
    files: dict[str, bytes] = {}
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        if path.name == "config.py":
            data = re.sub(rb'WORKER_VERSION = "[^"]+"', f'WORKER_VERSION = "{version}"'.encode(), data)
        files[str(Path("node_agent") / path.relative_to(PKG))] = data
    metadata = [
        "Metadata-Version: 2.1",
        "Name: agentmesh-worker",
        f"Version: {version}",
        "Summary: AgentMesh worker: contribute compute to AgentMesh",
        "License: MIT",
        "Requires-Python: >=3.11",
        *[f"Requires-Dist: {r}" for r in _requirements()],
    ]
    files[f"{dist_info}/METADATA"] = ("\n".join(metadata) + "\n").encode()
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: agentmesh-build\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files[f"{dist_info}/entry_points.txt"] = b"[console_scripts]\nagentmesh-worker = node_agent.cli:main\n"
    files[f"{dist_info}/top_level.txt"] = b"node_agent\n"
    record = [_record_line(name, data) for name, data in files.items()] + [f"{dist_info}/RECORD,,"]
    files[f"{dist_info}/RECORD"] = ("\n".join(record) + "\n").encode()

    out_dir.mkdir(parents=True, exist_ok=True)
    wheel = out_dir / f"{DIST_NAME}-{version}-py3-none-any.whl"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))  # reproducible
            info.external_attr = 0o644 << 16
            zf.writestr(info, data, zipfile.ZIP_DEFLATED)
    wheel.write_bytes(buf.getvalue())
    return wheel


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    path = build(target, sys.argv[2] if len(sys.argv) > 2 else None)
    print(path)
    print("sha256", hashlib.sha256(path.read_bytes()).hexdigest())
