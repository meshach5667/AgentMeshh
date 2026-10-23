"""Phase 7 production readiness: health/readiness, metrics, security headers, auth throttling, redaction."""

import logging

from app.core.config import settings
from app.core.logging import redact


async def test_liveness_readiness_and_security_headers(client):
    live = await client.get("/health")
    assert live.status_code == 200
    assert live.headers["x-content-type-options"] == "nosniff" and live.headers["x-frame-options"] == "DENY"
    ready = await client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["checks"] == {"database": "ok"}


async def test_metrics_need_a_token(client, monkeypatch, make_user):
    assert (await client.get("/metrics")).status_code == 404  # disabled without METRICS_TOKEN
    monkeypatch.setattr(settings, "METRICS_TOKEN", "m" * 32)
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    await make_user("customer")
    resp = await client.get("/metrics", headers={"Authorization": f"Bearer {'m' * 32}"})
    assert resp.status_code == 200
    body = resp.text
    assert "agentmesh_up 1" in body and 'agentmesh_http_requests_total{method="GET",status="4xx"}' in body
    assert "# TYPE agentmesh_payouts gauge" in body


async def test_login_is_throttled_per_account(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_PER_MINUTE", 3)
    user, _ = await make_user("customer")
    codes = [
        (await client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"})).status_code
        for _ in range(4)
    ]
    assert codes == [401, 401, 401, 429]
    blocked = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "correct-horse-battery"})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1


def test_paystack_keys_are_redacted_from_logs():
    from app.core.logging import JsonFormatter, RedactingFilter

    assert "abc123abc123" not in redact("Authorization: Bearer sk_test_abc123abc123")
    assert "1234567890abcdef" not in redact("key sk_live_1234567890abcdef")
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "calling paystack with %s", ("sk_test_" + "q" * 20,), None
    )
    RedactingFilter().filter(record)
    assert "q" * 20 not in JsonFormatter().format(record)
