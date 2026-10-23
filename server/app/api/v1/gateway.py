"""Inference gateway: authenticated, Ollama-compatible access to a customer's READY deployment.

    /api/v1/deployments/{id}/ollama/api/chat             POST  (Ollama native, streams NDJSON)
    /api/v1/deployments/{id}/ollama/api/generate         POST
    /api/v1/deployments/{id}/ollama/api/tags             GET   (answered by the control plane)
    /api/v1/deployments/{id}/ollama/v1/chat/completions  POST  (OpenAI-compatible, via Ollama)
    /api/v1/deployments/{id}/ollama/v1/completions       POST
    /api/v1/deployments/{id}/ollama/v1/models            GET

Requests are proxied through the worker's outbound tunnel. Prompts and responses are not logged or stored;
only request metadata and runtime-reported token counts are metered.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db, session_scope
from app.core.logging import current_request_id, new_request_id
from app.core.ratelimit import limiters
from app.core.security import ALGORITHM
from app.core.timeutil import utcnow
from app.models.api_key import ApiKey
from app.models.deployment import Deployment
from app.models.deployment import DeploymentStatus as S
from app.models.usage import UsageRecord
from app.models.user import Customer, User
from app.services.api_key_service import API_KEY_PREFIX, resolve_api_key
from app.services.tunnel import NodeUnavailable, broker

logger = logging.getLogger(__name__)
router = APIRouter()

# What each runtime serves. Only Ollama has the Ollama-native /api/* routes; every runtime serves the
# OpenAI-compatible /v1/* routes. Workers enforce the same allowlists.
OPENAI_POST = frozenset({"v1/chat/completions", "v1/completions"})
POST_PATHS = {
    "ollama": OPENAI_POST | {"api/chat", "api/generate"},
    "llamacpp": OPENAI_POST,
    "vllm": OPENAI_POST,
}
GET_PATHS = {
    "ollama": frozenset({"api/tags", "v1/models"}),
    "llamacpp": frozenset({"v1/models"}),
    "vllm": frozenset({"v1/models"}),
}


def _check_path(dep: Deployment, path: str, method: str, via_ollama_prefix: bool) -> None:
    runtime = dep.runtime or "ollama"
    if via_ollama_prefix and runtime != "ollama":
        raise GatewayError(
            404,
            "unsupported_endpoint",
            f"This deployment runs {runtime}; use /deployments/{dep.id}/v1/... (OpenAI-compatible)",
        )
    allowed = (POST_PATHS if method == "POST" else GET_PATHS).get(runtime, frozenset())
    if path not in allowed:
        raise GatewayError(404, "unsupported_endpoint", f"{method} /{path} is not supported by {runtime}")


USAGE_TAIL_BYTES = 64 * 1024


def gateway_error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}}, headers=headers)


class GatewayError(Exception):  # noqa: N818
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.response = gateway_error(status, code, message, headers)


async def _authenticate(request: Request, db: AsyncSession) -> tuple[User, ApiKey | None]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise GatewayError(401, "unauthorized", "Missing bearer credentials")
    token = auth[7:].strip()
    api_key = None
    if token.startswith(API_KEY_PREFIX):
        api_key = await resolve_api_key(db, token)
        if api_key is None:
            raise GatewayError(401, "unauthorized", "Invalid or revoked API key")
        if "inference" not in (api_key.scopes or []):
            raise GatewayError(403, "forbidden", "API key lacks the 'inference' scope")
        user = await db.get(User, api_key.user_id)
    else:
        try:
            user_id = uuid.UUID(str(jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM]).get("sub")))
        except (jwt.PyJWTError, ValueError):
            raise GatewayError(401, "unauthorized", "Invalid credentials") from None
        user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise GatewayError(401, "unauthorized", "Invalid credentials")
    return user, api_key


async def _resolve_deployment(db: AsyncSession, user: User, api_key: ApiKey | None, deployment_id: str) -> Deployment:
    not_found = GatewayError(404, "deployment_not_found", "Deployment not found")
    try:
        dep_uuid = uuid.UUID(deployment_id)
    except ValueError:
        raise not_found from None
    if api_key is not None and api_key.deployment_id is not None and api_key.deployment_id != dep_uuid:
        raise not_found
    customer = (await db.execute(select(Customer).where(Customer.user_id == user.id))).scalar_one_or_none()
    dep = await db.get(Deployment, dep_uuid)
    # Only the owning customer may call a deployment; staff accounts are deliberately not exempt here.
    if dep is None or customer is None or dep.customer_id != customer.id or dep.deleted_at is not None:
        raise not_found
    return dep


def _require_ready(dep: Deployment) -> None:
    status = S(dep.status)
    if status == S.UNHEALTHY:
        raise GatewayError(503, "deployment_unhealthy", "Deployment is unhealthy; retry later")
    if status != S.READY:
        raise GatewayError(409, "deployment_not_ready", f"Deployment is {status.value}, not READY")


async def _read_body(request: Request) -> dict:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.GATEWAY_MAX_BODY_BYTES:
        raise GatewayError(413, "request_too_large", f"Request body exceeds {settings.GATEWAY_MAX_BODY_BYTES} bytes")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > settings.GATEWAY_MAX_BODY_BYTES:
            raise GatewayError(
                413, "request_too_large", f"Request body exceeds {settings.GATEWAY_MAX_BODY_BYTES} bytes"
            )
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        raise GatewayError(400, "invalid_json", "Request body must be a JSON object") from None
    if not isinstance(data, dict):
        raise GatewayError(400, "invalid_json", "Request body must be a JSON object")
    return data


def _sanitize(path: str, body: dict, dep: Deployment) -> tuple[dict, bool]:
    """Pin the request to the deployment's model and limits. Returns (body, streaming)."""
    body = dict(body)
    body["model"] = dep.model_tag  # the node may cache other models; customers can only reach theirs
    body.pop("keep_alive", None)  # model residency is managed by the worker, not the caller
    num_ctx = (dep.config or {}).get("num_ctx")
    if path.startswith("api/"):
        raw_options = body.get("options")
        options: dict[str, Any] = dict(raw_options) if isinstance(raw_options, dict) else {}
        if num_ctx:
            options["num_ctx"] = num_ctx  # memory was reserved for this context size
        body["options"] = options
        streaming = body.get("stream", True) is not False
    else:
        streaming = body.get("stream") is True
        if streaming and "stream_options" not in body:
            # Ask the runtime to append token usage to the stream so it can be metered.
            body["stream_options"] = {"include_usage": True}
    return body, streaming


def _parse_usage(path: str, tail: bytes) -> tuple[int | None, int | None]:
    """Extract runtime-reported token counts from the end of a response. Returns (None, None) when the
    runtime did not report them; counts are never estimated."""
    text = tail.decode("utf-8", errors="ignore")
    candidates = []
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            candidates.append(obj)
            if len(candidates) > 4:
                break
    for obj in candidates:
        if "eval_count" in obj or "prompt_eval_count" in obj:
            return obj.get("prompt_eval_count"), obj.get("eval_count")
        usage = obj.get("usage")
        if isinstance(usage, dict) and ("prompt_tokens" in usage or "completion_tokens" in usage):
            return usage.get("prompt_tokens"), usage.get("completion_tokens")
    return None, None


async def _record_usage(**fields) -> None:
    try:
        async with session_scope() as db:
            db.add(UsageRecord(kind="inference", period_start=fields.pop("started"), period_end=utcnow(), **fields))
            if fields.get("api_key_id"):
                key = await db.get(ApiKey, fields["api_key_id"])
                if key is not None:
                    key.last_used_at = utcnow()
            await db.commit()
    except IntegrityError:
        pass  # duplicate request_id: already recorded
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record usage for request %s", fields.get("request_id"))


@router.get("/{deployment_id}/ollama/{path:path}")
async def gateway_get(deployment_id: str, path: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _gateway_get(deployment_id, path, request, db, via_ollama_prefix=True)


@router.get("/{deployment_id}/v1/{path:path}")
async def gateway_get_openai(deployment_id: str, path: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _gateway_get(deployment_id, f"v1/{path}", request, db, via_ollama_prefix=False)


@router.post("/{deployment_id}/ollama/{path:path}")
async def gateway_post(deployment_id: str, path: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _gateway_post(deployment_id, path, request, db, via_ollama_prefix=True)


@router.post("/{deployment_id}/v1/{path:path}")
async def gateway_post_openai(deployment_id: str, path: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await _gateway_post(deployment_id, f"v1/{path}", request, db, via_ollama_prefix=False)


async def _gateway_get(deployment_id: str, path: str, request: Request, db: AsyncSession, via_ollama_prefix: bool):
    try:
        user, api_key = await _authenticate(request, db)
        dep = await _resolve_deployment(db, user, api_key, deployment_id)
        _check_path(dep, path, "GET", via_ollama_prefix)
        _require_ready(dep)
    except GatewayError as exc:
        return exc.response
    if path == "api/tags":
        return {"models": [{"name": dep.model_tag, "model": dep.model_tag, "digest": dep.model_digest}]}
    created = int((dep.ready_at or dep.created_at).timestamp())
    return {
        "object": "list",
        "data": [{"id": dep.model_tag, "object": "model", "created": created, "owned_by": "agentmesh"}],
    }


async def _gateway_post(deployment_id: str, path: str, request: Request, db: AsyncSession, via_ollama_prefix: bool):
    try:
        user, api_key = await _authenticate(request, db)
        dep = await _resolve_deployment(db, user, api_key, deployment_id)
        _check_path(dep, path, "POST", via_ollama_prefix)
        _require_ready(dep)
        principal = f"key:{api_key.id}" if api_key else f"user:{user.id}"
        allowed, retry_after = await limiters.requests.allow(principal, settings.GATEWAY_RATE_LIMIT_PER_MINUTE)
        if not allowed:
            raise GatewayError(
                429, "rate_limited", "Too many requests", headers={"Retry-After": str(max(1, int(retry_after)))}
            )
        body, streaming = _sanitize(path, await _read_body(request), dep)
    except GatewayError as exc:
        return exc.response

    concurrency_key = str(dep.id)
    if not await limiters.concurrency.acquire(concurrency_key, settings.GATEWAY_MAX_CONCURRENT_PER_DEPLOYMENT):
        return gateway_error(429, "too_many_concurrent_requests", "Deployment is at its concurrent request limit")

    request_id = current_request_id() or new_request_id()
    started = utcnow()
    t0 = time.monotonic()
    meter = {
        "request_id": request_id,
        "deployment_id": dep.id,
        "node_id": dep.node_id,
        "api_key_id": api_key.id if api_key else None,
        "endpoint": path,
        "started": started,
    }
    frame = {
        "type": "request",
        "id": request_id,
        "deployment_id": str(dep.id),
        "method": "POST",
        "path": "/" + path,
        "body": body,
    }

    try:
        conn, rid, queue = await broker.open_request(dep.node_id, frame)
    except NodeUnavailable:
        await limiters.concurrency.release(concurrency_key)
        await _record_usage(**meter, status_code=503, outcome="node_unavailable", duration_ms=0)
        return gateway_error(503, "node_unavailable", "The node serving this deployment is not connected")

    try:
        first = await asyncio.wait_for(queue.get(), timeout=settings.GATEWAY_FIRST_BYTE_TIMEOUT_SECONDS)
    except TimeoutError:
        first = {"type": "error", "code": "timeout", "message": "Runtime did not respond in time"}
    if first.get("type") != "response_start":
        broker.close_request(conn, rid)
        await limiters.concurrency.release(concurrency_key)
        outcome = "timeout" if first.get("code") == "timeout" else "node_unavailable"
        if outcome == "timeout":
            await _safe_cancel(conn, rid)
        status = 504 if outcome == "timeout" else 502
        await _record_usage(
            **meter, status_code=status, outcome=outcome, duration_ms=int((time.monotonic() - t0) * 1000)
        )
        return gateway_error(status, first.get("code") or "runtime_error", first.get("message") or "Runtime error")

    upstream_status = int(first.get("status", 502))
    media_type = first.get("content_type") or ("application/x-ndjson" if streaming else "application/json")
    if media_type not in ("application/x-ndjson", "application/json", "text/event-stream", "text/plain"):
        media_type = "application/octet-stream"

    async def relay():
        tail = bytearray()
        total = 0
        outcome = "success" if upstream_status < 400 else "runtime_error"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=settings.GATEWAY_IDLE_TIMEOUT_SECONDS)
                except TimeoutError:
                    outcome = "timeout"
                    await _safe_cancel(conn, rid)
                    break
                kind = msg.get("type")
                if kind == "chunk":
                    data = str(msg.get("data", "")).encode()
                    total += len(data)
                    if total > settings.GATEWAY_MAX_RESPONSE_BYTES:
                        outcome = "runtime_error"
                        await _safe_cancel(conn, rid)
                        break
                    tail.extend(data)
                    del tail[:-USAGE_TAIL_BYTES]
                    yield data
                elif kind == "response_end":
                    break
                else:  # error mid-stream
                    outcome = "node_unavailable" if msg.get("code") == "node_disconnected" else "runtime_error"
                    break
        except (asyncio.CancelledError, GeneratorExit):
            outcome = "cancelled"
            await _safe_cancel(conn, rid)
            raise
        finally:
            broker.close_request(conn, rid)
            await limiters.concurrency.release(concurrency_key)
            prompt_tokens, completion_tokens = _parse_usage(path, bytes(tail)) if outcome == "success" else (None, None)
            await _record_usage(
                **meter,
                status_code=upstream_status,
                outcome=outcome,
                duration_ms=int((time.monotonic() - t0) * 1000),
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                token_source="runtime_reported" if prompt_tokens is not None or completion_tokens is not None else None,
                response_bytes=total,
            )

    return StreamingResponse(
        relay(), status_code=upstream_status, media_type=media_type, headers={"X-AgentMesh-Request-Id": request_id}
    )


async def _safe_cancel(conn, request_id: str) -> None:
    try:
        await conn.send({"type": "cancel", "id": request_id})
    except Exception:  # noqa: BLE001
        pass
