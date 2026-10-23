"""Inference request queue between the control plane and internal inference machines.

Inference machines (see the ``ai_adapter`` package) connect outbound, report health, lease requests, run
them on their local Ollama, and post results back. The control plane never connects to them, so they need no
public address, and Ollama stays bound to localhost.

When no machine is connected, requests wait here (bounded by AI_QUEUE_MAX_LENGTH) until they expire after
AI_QUEUE_TTL_SECONDS. A lease that is not answered within AI_REQUEST_TIMEOUT is handed out again, at most
AI_MAX_ATTEMPTS times. A request is never answered by a model other than OLLAMA_MODEL.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db_utils import rowcount
from app.core.logging import redact
from app.core.timeutil import utcnow
from app.models.ai import AiInferenceNode, AiInferenceRequest

OPEN = ("PENDING", "LEASED")
MAX_RESULT_CHARS = 16_000


class QueueFull(Exception):  # noqa: N818
    pass


def options() -> dict[str, Any]:
    """Generation limits sent with every request. Adapters clamp them again to their own limits."""
    return {"num_ctx": settings.AI_NUM_CTX, "num_predict": settings.AI_MAX_TOKENS, "temperature": 0}


async def depth(db: AsyncSession) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(AiInferenceRequest).where(AiInferenceRequest.status.in_(OPEN))
            )
        ).scalar()
        or 0
    )


async def enqueue(
    db: AsyncSession, *, run_id: uuid.UUID | None, purpose: str, messages: list[dict], schema: dict
) -> AiInferenceRequest:
    """Queue one model call. Raises QueueFull when the queue is at its limit. Does not commit."""
    if await depth(db) >= settings.AI_QUEUE_MAX_LENGTH:
        raise QueueFull("The AI service queue is full")
    now = utcnow()
    req = AiInferenceRequest(
        id=uuid.uuid4(),
        run_id=run_id,
        purpose=purpose,
        model=settings.OLLAMA_MODEL,
        payload={"messages": messages, "format": schema, "options": options()},
        status="PENDING",
        max_attempts=settings.AI_MAX_ATTEMPTS,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.AI_QUEUE_TTL_SECONDS),
    )
    db.add(req)
    await db.flush()
    return req


async def cancel(db: AsyncSession, request_id: uuid.UUID | None) -> None:
    if request_id is None:
        return
    await db.execute(
        update(AiInferenceRequest)
        .where(AiInferenceRequest.id == request_id, AiInferenceRequest.status.in_(OPEN))
        .values(status="CANCELLED", payload=None, completed_at=utcnow())
        .execution_options(synchronize_session=False)
    )


# --- Inference machine health --------------------------------------------------------------------------


@dataclass
class Health:
    status: str  # available | degraded | unavailable | not_configured
    model: str
    queue_depth: int
    message: str
    nodes: list[AiInferenceNode] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.status == "available"


def node_is_fresh(node: AiInferenceNode, now: datetime | None = None) -> bool:
    return (now or utcnow()) - node.last_seen <= timedelta(seconds=settings.AI_NODE_TIMEOUT_SECONDS)


def node_can_serve(node: AiInferenceNode, now: datetime | None = None) -> bool:
    return (
        node_is_fresh(node, now)
        and node.ollama_ok
        and node.model_ready
        and node.accepting
        and node.model == settings.OLLAMA_MODEL
    )


async def health(db: AsyncSession) -> Health:
    now = utcnow()
    queued = await depth(db)
    if not settings.AI_INFERENCE_TOKEN:
        return Health("not_configured", settings.OLLAMA_MODEL, queued, "No AI inference machine is configured.")
    nodes = list((await db.execute(select(AiInferenceNode).order_by(AiInferenceNode.id))).scalars().all())
    fresh = [n for n in nodes if node_is_fresh(n, now)]
    if any(node_can_serve(n, now) for n in fresh):
        return Health("available", settings.OLLAMA_MODEL, queued, "The AI service is available.", nodes)
    if not fresh:
        msg = "The AI inference machine is offline. AI requests are queued until it reconnects."
        return Health("unavailable", settings.OLLAMA_MODEL, queued, msg, nodes)
    return Health(
        "degraded",
        settings.OLLAMA_MODEL,
        queued,
        "The AI inference machine is connected but not accepting work (busy, overloaded, or the model is not ready).",
        nodes,
    )


async def heartbeat(db: AsyncSession, node_id: str, report: dict[str, Any]) -> AiInferenceNode:
    now = utcnow()
    node = await db.get(AiInferenceNode, node_id)
    if node is None:
        node = AiInferenceNode(id=node_id, created_at=now, last_seen=now)
        db.add(node)
    node.last_seen = now
    node.model = report.get("model")
    node.ollama_version = report.get("ollama_version")
    node.ollama_ok = bool(report.get("ollama_ok"))
    node.model_ready = bool(report.get("model_ready"))
    node.accepting = bool(report.get("accepting"))
    node.reason = report.get("reason")
    node.metrics = report.get("metrics") or {}
    node.in_flight = int(report.get("in_flight") or 0)
    if node.model != settings.OLLAMA_MODEL:
        node.accepting = False
        node.reason = f"serves {node.model or 'no model'}, expected {settings.OLLAMA_MODEL}"
    await db.commit()
    return node


# --- Leases --------------------------------------------------------------------------------------------


async def lease(db: AsyncSession, node: AiInferenceNode, max_requests: int) -> list[AiInferenceRequest]:
    """Hand out up to ``max_requests`` queued requests, within the global AI_MAX_CONCURRENT_REQUESTS limit."""
    now = utcnow()
    if not node_can_serve(node, now):
        return []
    in_flight = (
        await db.execute(
            select(func.count())
            .select_from(AiInferenceRequest)
            .where(AiInferenceRequest.status == "LEASED", AiInferenceRequest.lease_expires_at >= now)
        )
    ).scalar() or 0
    room = min(max_requests, settings.AI_MAX_CONCURRENT_REQUESTS - int(in_flight))
    if room <= 0:
        return []
    candidates = (
        (
            await db.execute(
                select(AiInferenceRequest)
                .where(
                    AiInferenceRequest.status == "PENDING",
                    AiInferenceRequest.expires_at > now,
                    AiInferenceRequest.model == node.model,
                )
                .order_by(AiInferenceRequest.created_at)
                .limit(room)
            )
        )
        .scalars()
        .all()
    )
    leased = []
    for req in candidates:
        claimed = await db.execute(
            update(AiInferenceRequest)
            .where(AiInferenceRequest.id == req.id, AiInferenceRequest.status == "PENDING")
            .values(
                status="LEASED",
                attempts=req.attempts + 1,
                node_id=node.id,
                lease_expires_at=now + timedelta(seconds=settings.AI_REQUEST_TIMEOUT),
            )
            .execution_options(synchronize_session=False)
        )
        if rowcount(claimed) == 1:
            leased.append(req)
    await db.commit()
    return leased


async def complete(
    db: AsyncSession,
    node_id: str,
    request_id: uuid.UUID,
    *,
    content: str | None,
    error_code: str | None,
    error: str | None,
    retryable: bool,
    latency_ms: int | None,
    prompt_tokens: int | None,
    output_tokens: int | None,
    model: str | None,
) -> AiInferenceRequest | None:
    """Record the answer to a leased request. Returns None if the lease is no longer this node's (expired and
    re-leased, cancelled): such late answers are discarded. Does not commit."""
    req = await db.get(AiInferenceRequest, request_id)
    if req is None or req.status != "LEASED" or req.node_id != node_id:
        return None
    now = utcnow()
    values: dict[str, Any] = {"latency_ms": latency_ms, "lease_expires_at": None}
    if content is not None and error_code is None:
        if model != req.model:
            error_code, error, retryable = "MODEL_MISMATCH", f"answered by {model}, expected {req.model}", False
        else:
            values.update(
                status="COMPLETED",
                result={
                    "content": content[:MAX_RESULT_CHARS],
                    "prompt_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                },
                payload=None,
                completed_at=now,
            )
    if "status" not in values:
        if retryable and req.attempts < req.max_attempts and req.expires_at > now:
            values.update(status="PENDING", node_id=None)
        else:
            values.update(status="FAILED", payload=None, completed_at=now)
        values.update(error_code=(error_code or "INFERENCE_ERROR")[:50], error=redact(error or "")[:500])
    result = await db.execute(
        update(AiInferenceRequest)
        .where(
            AiInferenceRequest.id == req.id,
            AiInferenceRequest.status == "LEASED",
            AiInferenceRequest.node_id == node_id,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if rowcount(result) != 1:
        return None
    for key, value in values.items():
        setattr(req, key, value)
    return req


async def expire(db: AsyncSession, now: datetime | None = None) -> set[uuid.UUID]:
    """Expire requests that waited too long and re-queue (or fail) unanswered leases. Returns the runs
    affected. Does not commit."""
    now = now or utcnow()
    runs: set[uuid.UUID] = set()
    stale = (
        (
            await db.execute(
                select(AiInferenceRequest).where(
                    AiInferenceRequest.status == "LEASED", AiInferenceRequest.lease_expires_at < now
                )
            )
        )
        .scalars()
        .all()
    )
    for req in stale:
        retry = req.attempts < req.max_attempts and req.expires_at > now
        values: dict[str, Any] = (
            {"status": "PENDING", "node_id": None, "lease_expires_at": None}
            if retry
            else {"status": "FAILED", "payload": None, "completed_at": now}
        )
        values.update(error_code="TIMEOUT", error="The inference machine did not answer in time")
        await db.execute(
            update(AiInferenceRequest)
            .where(AiInferenceRequest.id == req.id, AiInferenceRequest.status == "LEASED")
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if not retry and req.run_id:
            runs.add(req.run_id)
    waiting = (
        (
            await db.execute(
                select(AiInferenceRequest).where(
                    AiInferenceRequest.status == "PENDING", AiInferenceRequest.expires_at <= now
                )
            )
        )
        .scalars()
        .all()
    )
    for req in waiting:
        await db.execute(
            update(AiInferenceRequest)
            .where(AiInferenceRequest.id == req.id, AiInferenceRequest.status == "PENDING")
            .values(
                status="EXPIRED",
                payload=None,
                completed_at=now,
                error_code="EXPIRED",
                error="No inference machine answered before the request expired",
            )
            .execution_options(synchronize_session=False)
        )
        if req.run_id:
            runs.add(req.run_id)
    return runs
