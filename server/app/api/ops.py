"""Operational endpoints outside /api/v1: liveness, readiness, and Prometheus metrics."""

import hmac
import time
from collections import Counter

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import session_scope
from app.models.billing import Payment, Payout
from app.models.deployment import Deployment
from app.models.node import Node

router = APIRouter()
STARTED = time.time()
# Filled by the request middleware in app.main: (method, status class) -> count.
http_requests: Counter = Counter()


@router.get("/health", tags=["Health"])
async def health_check():
    """Liveness: the process is serving. Does not touch dependencies."""
    return {"status": "ok", "service": "agentmesh-api", "version": "0.1.0"}


@router.get("/health/ready", tags=["Health"])
async def readiness():
    """Readiness: the database (and Redis, when used for coordination) answer. 503 otherwise."""
    checks: dict[str, str] = {}
    try:
        async with session_scope() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
    if settings.COORDINATION_BACKEND == "redis":
        from app.services.tunnel import broker

        try:
            redis = getattr(broker.coordinator, "redis", None)
            checks["redis"] = "ok" if redis is not None and await redis.ping() else "error: not connected"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        raise HTTPException(status_code=503, detail={"status": "unavailable", "checks": checks})
    return {"status": "ready", "checks": checks}


def _line(name: str, value: float, **labels: str) -> str:
    lab = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{lab}}} {value}" if lab else f"{name} {value}"


@router.get("/metrics", include_in_schema=False)
async def metrics(authorization: str = Header(default="")):
    """Prometheus text format. Requires ``Authorization: Bearer <METRICS_TOKEN>``; disabled when unset."""
    if not settings.METRICS_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token.encode(), settings.METRICS_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    out = [
        "# TYPE agentmesh_up gauge",
        "agentmesh_up 1",
        "# TYPE agentmesh_uptime_seconds gauge",
        _line("agentmesh_uptime_seconds", round(time.time() - STARTED, 1)),
        "# TYPE agentmesh_http_requests_total counter",
    ]
    out += [
        _line("agentmesh_http_requests_total", n, method=m, status=s) for (m, s), n in sorted(http_requests.items())
    ]
    async with session_scope() as db:
        for metric, column in (
            ("agentmesh_nodes", Node.status),
            ("agentmesh_deployments", Deployment.status),
            ("agentmesh_payments", Payment.status),
            ("agentmesh_payouts", Payout.status),
        ):
            out.append(f"# TYPE {metric} gauge")
            rows = (await db.execute(select(column, func.count()).group_by(column))).all()
            out += [_line(metric, n, status=str(getattr(k, "value", k))) for k, n in rows if k is not None]
    return Response("\n".join(out) + "\n", media_type="text/plain; version=0.0.4")


SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    """Adds security headers and counts responses. Pure ASGI, so streaming responses pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                extra = SECURITY_HEADERS + ([] if settings.is_dev else [HSTS])
                headers += [(k, v) for k, v in extra if k not in present]
                message["headers"] = headers
                http_requests[(scope["method"], f"{message['status'] // 100}xx")] += 1
            await send(message)

        await self.app(scope, receive, send_with_headers)
