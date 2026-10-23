"""Node keypair. The public key is registered at enrollment for future signed messages and attestation;
protocol v1 authenticates with the node credential only."""

import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _paths(data_dir: Path) -> tuple[Path, Path]:
    return data_dir / "node_key.pem", data_dir / "node_key.pub"


def generate_keypair(data_dir: Path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    priv_path, pub_path = _paths(data_dir)
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(
            private_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
    pub_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return private_key, private_key.public_key()


def load_identity(data_dir: Path):
    priv_path, _ = _paths(data_dir)
    if not priv_path.exists():
        return None, None
    private_key = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    return private_key, private_key.public_key()


def get_or_create_identity(data_dir: Path):
    priv, pub = load_identity(data_dir)
    if priv is None:
        priv, pub = generate_keypair(data_dir)
    return priv, pub


def get_public_key_pem(public_key) -> str:
    return public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(
        "utf-8"
    )


def sign_message(private_key, message: bytes) -> bytes:
    return private_key.sign(
        message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256()
    )
