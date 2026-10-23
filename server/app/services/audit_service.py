"""Audit trail for security-relevant actions by customers, providers, operators, and workers.

Rows are added to the caller's transaction (no commit here), so an action and its audit record are saved
together or not at all. Secrets and prompt contents never go into ``details``.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import client_ip_var, redact, request_id_var
from app.models.audit import AuditLog


def record(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: Any,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    safe = {k: redact(v) if isinstance(v, str) else v for k, v in (details or {}).items()}
    if request_id_var.get():
        safe["request_id"] = request_id_var.get()
    entry = AuditLog(
        user_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=safe,
        ip_address=client_ip_var.get(),
    )
    db.add(entry)
    return entry


async def search(
    db: AsyncSession,
    *,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 500))
    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)
    if actor_id:
        query = query.where(AuditLog.user_id == actor_id)
    return list((await db.execute(query)).scalars().all())
