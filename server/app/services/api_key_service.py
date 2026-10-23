from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.core.security import generate_secret, hash_secret
from app.core.timeutil import utcnow
from app.models.api_key import ApiKey
from app.models.user import User
from app.services import audit_service

API_KEY_PREFIX = "am_sk_"
SCOPES = frozenset({"inference"})


async def create_api_key(
    db: AsyncSession, user: User, name: str, scopes: list[str], deployment_id: str | None, expires_at: datetime | None
) -> tuple[ApiKey, str]:
    unknown = set(scopes) - SCOPES
    if unknown or not scopes:
        raise HTTPException(status_code=422, detail=f"Scopes must be a non-empty subset of {sorted(SCOPES)}")
    dep_uuid = None
    if deployment_id:
        from app.services.deployment_service import get_deployment_for_user

        dep_uuid = (await get_deployment_for_user(db, deployment_id, user)).id
    secret = generate_secret(API_KEY_PREFIX)
    key = ApiKey(
        user_id=user.id,
        name=name,
        prefix=secret[: len(API_KEY_PREFIX) + 6],
        key_hash=hash_secret(secret),
        scopes=sorted(set(scopes)),
        deployment_id=dep_uuid,
        expires_at=expires_at,
    )
    db.add(key)
    await db.flush()
    audit_service.record(
        db,
        actor_id=user.id,
        action="api_key.created",
        resource_type="api_key",
        resource_id=key.id,
        details={"name": name, "scopes": key.scopes, "deployment_id": str(dep_uuid) if dep_uuid else None},
    )
    await db.commit()
    await db.refresh(key)
    return key, secret


async def list_api_keys(db: AsyncSession, user: User) -> list[ApiKey]:
    result = await db.execute(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc()))
    return list(result.scalars().all())


async def revoke_api_key(db: AsyncSession, user: User, key_id: str) -> ApiKey:
    key = await db.get(ApiKey, parse_uuid(key_id, "API key"))
    if key is None or key.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        audit_service.record(
            db, actor_id=user.id, action="api_key.revoked", resource_type="api_key", resource_id=key.id
        )
        await db.commit()
    return key


async def resolve_api_key(db: AsyncSession, secret: str) -> ApiKey | None:
    """Return the active key for ``secret``, or None. Lookup is by hash; the plaintext is never stored."""
    if not secret.startswith(API_KEY_PREFIX):
        return None
    key = (await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_secret(secret)))).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return None
    if key.expires_at is not None and key.expires_at <= utcnow():
        return None
    return key
