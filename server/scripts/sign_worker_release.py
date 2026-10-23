"""Create the release signing key and sign worker release manifests. Keep the private key OFF the server.

    python scripts/sign_worker_release.py keygen --out release-key.pem      # prints the public key to pin
    python scripts/sign_worker_release.py sign --key release-key.pem --wheel dist/agentmesh_worker-0.3.1-....whl \\
        --out-dir /srv/agentmesh/releases

The control plane serves WORKER_RELEASE_DIR/manifest.json, manifest.sig, and the wheel. Workers verify the
signature against AGENTMESH_UPDATE_PUBLIC_KEY before downloading anything else.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def keygen(out: Path) -> None:
    key = Ed25519PrivateKey.generate()
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print(base64.b64encode(pub).decode())


def sign(key_path: Path, wheel: Path, out_dir: Path) -> None:
    m = re.fullmatch(r"agentmesh_worker-(\d+\.\d+\.\d+)-py3-none-any\.whl", wheel.name)
    if not m:
        raise SystemExit("wheel name must be agentmesh_worker-X.Y.Z-py3-none-any.whl")
    data = wheel.read_bytes()
    manifest = json.dumps(
        {"version": m[1], "wheel": wheel.name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)},
        sort_keys=True,
    ).encode()
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("not an Ed25519 key")
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wheel, out_dir / wheel.name)
    (out_dir / "manifest.json").write_bytes(manifest)
    (out_dir / "manifest.sig").write_text(base64.b64encode(key.sign(manifest)).decode())
    print(f"Signed {wheel.name} -> {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("sign")
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--wheel", type=Path, required=True)
    s.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()
    keygen(a.out) if a.cmd == "keygen" else sign(a.key, a.wheel, a.out_dir)
