"""Correlation ids, secret redaction, and the audit trail."""

import json
import logging

from app.core.logging import JsonFormatter, RedactingFilter, redact


def test_redaction_of_all_secret_kinds():
    text = (
        "key am_sk_AbCdEf123456789 node am_node_XyZ987654321abc enroll am_enroll_qwertyuiop12345 "
        'header Bearer eyJhbGciOiJIUzI1NiJ9.abc.def json {"password": "hunter2hunter2"}'
    )
    out = redact(text)
    for secret in ("AbCdEf123456789", "XyZ987654321abc", "qwertyuiop12345", "eyJhbGciOiJIUzI1NiJ9", "hunter2hunter2"):
        assert secret not in out
    assert out.count("[REDACTED]") == 5


def test_log_records_are_redacted_and_carry_request_id(caplog):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "using %s", ("am_sk_supersecretvalue123",), None)
    RedactingFilter().filter(record)
    line = json.loads(JsonFormatter().format(record))
    assert "supersecretvalue" not in line["message"] and line["request_id"] == "-"


async def test_every_response_gets_a_server_generated_request_id(client):
    resp = await client.get("/health", headers={"X-Request-ID": "client-chosen-id-1234"})
    rid = resp.headers["x-request-id"]
    assert rid != "client-chosen-id-1234" and len(rid) == 32


async def test_gateway_meters_with_request_id_even_if_client_replays_header(
    client, db, make_user, enroll_node, ollama_model
):
    """A client cannot suppress metering by reusing an X-Request-ID."""
    from sqlalchemy import select

    from app.models import UsageRecord
    from tests.test_gateway import FakeWorker

    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)).json()
    await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status", json={"state": "READY"}, headers=node["headers"]
    )
    from app.services.tunnel import broker

    worker = FakeWorker(node["node_id"])
    await broker.register(worker.conn)
    try:
        h = {**customer, "X-Request-ID": "same-id-every-time"}
        for _ in range(2):
            resp = await client.post(f"/api/v1/deployments/{dep['id']}/ollama/api/chat", json={}, headers=h)
            assert resp.status_code == 200
            assert resp.headers["x-agentmesh-request-id"] == resp.headers["x-request-id"]
    finally:
        broker.unregister(worker.conn)
    rows = (await db.execute(select(UsageRecord))).scalars().all()
    assert len(rows) == 2 and len({r.request_id for r in rows}) == 2


async def test_audit_trail_records_sensitive_actions(client, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)).json()
    key = (await client.post("/api/v1/api-keys", json={"name": "k"}, headers=customer)).json()
    await client.delete(f"/api/v1/api-keys/{key['id']}", headers=customer)
    await client.post(f"/api/v1/deployments/{dep['id']}/stop", headers=customer)
    await client.patch(
        f"/api/v1/nodes/{node['node_id']}", json={"accepting_workloads": False}, headers=node["provider_headers"]
    )
    await client.post(f"/api/v1/nodes/{node['node_id']}/revoke", headers=node["provider_headers"])
    await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})

    assert (await client.get("/api/v1/admin/audit-logs", headers=customer)).status_code == 403
    _, operator = await make_user("operator")
    logs = (await client.get("/api/v1/admin/audit-logs?limit=500", headers=operator)).json()
    actions = {entry["action"] for entry in logs}
    assert {
        "node.enrollment_token_created",
        "node.enrolled",
        "deployment.created",
        "api_key.created",
        "api_key.revoked",
        "deployment.stopped",
        "node.paused",
        "node.revoked",
        "auth.login_failed",
    } <= actions
    # Every entry from an HTTP request carries its correlation id; no secret ever appears.
    assert all("request_id" in (e["details"] or {}) for e in logs)
    assert key["key"] not in json.dumps(logs)
    revoked = (
        await client.get(
            f"/api/v1/admin/audit-logs?action=node.revoked&resource_id={node['node_id']}", headers=operator
        )
    ).json()
    assert len(revoked) == 1


async def test_deployment_move_is_audited(client, make_user, enroll_node, ollama_model):
    _, provider = await make_user("provider")
    a = await enroll_node(provider=provider, ram_mb=8192)
    await enroll_node(provider=provider, ram_mb=4096)
    _, customer = await make_user("customer")
    dep = (await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)).json()
    await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status",
        json={"state": "FAILED", "error_code": "INSUFFICIENT_MEMORY"},
        headers=a["headers"],
    )
    _, operator = await make_user("operator")
    moves = (await client.get("/api/v1/admin/audit-logs?action=deployment.moved", headers=operator)).json()
    assert moves[0]["details"]["from_node"] == a["node_id"]
    assert moves[0]["details"]["reason"] == "INSUFFICIENT_MEMORY"
