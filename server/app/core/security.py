import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.timeutil import utcnow

pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def verify_password(plain_password, hashed_password):
    return bool(pwd_context.verify(plain_password, hashed_password))


def get_password_hash(password):
    return pwd_context.hash(password)


SHA256_PREFIX = "sha256$"


def generate_secret(prefix: str, nbytes: int = 32) -> str:
    """High-entropy bearer secret, e.g. ``am_sk_...``. Never stored in plaintext."""
    return f"{prefix}{secrets.token_urlsafe(nbytes)}"


def hash_secret(secret: str) -> str:
    """Hash a high-entropy machine secret. SHA-256 is appropriate here (unlike for passwords) because the
    secret has ~256 bits of entropy and must be verified on every request."""
    return SHA256_PREFIX + hashlib.sha256(secret.encode()).hexdigest()


def verify_secret(secret: str, stored_hash: str | None) -> bool:
    if not stored_hash or not stored_hash.startswith(SHA256_PREFIX):
        return False
    return hmac.compare_digest(hash_secret(secret), stored_hash)


def verify_node_api_key(plain_key: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith(SHA256_PREFIX):
        return verify_secret(plain_key, stored_hash)
    # Legacy keys issued by POST /nodes/register before Phase 2 were hashed with the password context.
    try:
        return bool(pwd_context.verify(plain_key, stored_hash))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str | Any, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = utcnow() + expires_delta
    else:
        expire = utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": str(subject)}
    return str(jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM))
