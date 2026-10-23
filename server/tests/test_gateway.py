"""Inference gateway, API keys, and metering. A fake worker is attached to the real tunnel broker."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import ApiKey, UsageRecord
from app.services.tunnel import WorkerConnection, broker
from node_agent.tunnel import TunnelHandler

PROMPT = "a very secret prompt 7f3a"
NDJSON = [
    {"model": "qwen2.5:0.5b", "message": {"role": "assistant", "content": "Hel"}, "done": False},
    {"model": "qwen2.5:0.5b", "message": {"role": "assistant", "content": "lo"}, "done": False},
    {"model": "qwen2.5:0.5b", "done": True, "prompt_eval_count": 12, "eval_count": 2},
]


class FakeWorker:
    """Answers tunnel requests like a worker would, and records what it received."""

    def __init__(self, node_id, mode="ok"):
        self.node_id = uuid.UUID(str(node_id))
        self.mode = mode
        self.received: list[dict] = []
        self.cancelled: list[str] = []
        self.conn = WorkerConnection(node_id=self.node_id, send_json=self._on_send, close=self._close)

    async def _close(self):
        pass

    async def _on_send(self, frame):
        if frame["type"] == "cancel":
            self.cancelled.append(frame["id"])
            return
        self.received.append(frame)
        asyncio.get_running_loop().create_task(self._respond(frame["id"]))

    async def _respond(self, rid):
        d = self.conn.dispatch
        if self.mode == "silent":
            return
        d({"type": "response_start", "id": rid, "status": 200, "content_type": "application/x-ndjson"})
        lines = [json.dumps(x) + "\n" for x in NDJSON]
        if self.mode == "error_midstream":
            d({"type": "chunk", "id": rid, "data": lines[0]})
            d({"type": "error", "id": rid, "code": "runtime_error", "message": "boom"})
            return
        for line in lines:
            await asyncio.sleep(0)
            d({"type": "chunk", "id": rid, "data": line})
        d({"type": "response_end", "id": rid})


@pytest.fixture
async def ready_deployment(client, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    user, customer = await make_user("customer")
    dep = (await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)).json()
    r = await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status", json={"state": "READY"}, headers=node["headers"]
    )
    assert r.status_code == 200
    worker = FakeWorker(node["node_id"])
    await broker.register(worker.conn)
    yield {"dep": dep, "customer": customer, "user": user, "node": node, "worker": worker}
    broker.unregister(worker.conn)


async def _key(client, headers, **body):
    resp = await client.post("/api/v1/api-keys", json={"name": "k", **body}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _url(dep_id, path="api/chat"):
    return f"/api/v1/deployments/{dep_id}/ollama/{path}"


async def test_api_key_lifecycle_and_hash_storage(client, db, make_user):
    _, customer = await make_user("customer")
    created = await _key(client, customer)
    assert created["key"].startswith("am_sk_")
    listed = (await client.get("/api/v1/api-keys", headers=customer)).json()
    assert "key" not in listed[0] and listed[0]["prefix"] == created["prefix"]
    row = (await db.execute(select(ApiKey))).scalars().one()
    assert created["key"] not in row.key_hash
    revoked = await client.delete(f"/api/v1/api-keys/{created['id']}", headers=customer)
    assert revoked.json()["revoked_at"] is not None
    _, other = await make_user("customer")
    assert (await client.delete(f"/api/v1/api-keys/{created['id']}", headers=other)).status_code == 404
    _, provider = await make_user("provider")
    assert (await client.post("/api/v1/api-keys", json={"name": "x"}, headers=provider)).status_code == 403
    assert (
        await client.post("/api/v1/api-keys", json={"name": "x", "scopes": ["admin"]}, headers=customer)
    ).status_code == 422


async def test_streaming_chat_relays_pins_model_and_meters(client, db, ready_deployment):
    dep, worker = ready_deployment["dep"], ready_deployment["worker"]
    key = await _key(client, ready_deployment["customer"])
    body = {
        "model": "someone-elses-model",
        "messages": [{"role": "user", "content": PROMPT}],
        "keep_alive": -1,
        "options": {"num_ctx": 131072, "temperature": 0.1},
    }
    resp = await client.post(_url(dep["id"]), json=body, headers={"Authorization": f"Bearer {key['key']}"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(x) for x in resp.text.splitlines()]
    assert lines == NDJSON

    sent = worker.received[0]["body"]
    assert sent["model"] == "qwen2.5:0.5b"  # pinned to the deployment
    assert "keep_alive" not in sent
    assert sent["options"]["num_ctx"] == 2048 and sent["options"]["temperature"] == 0.1

    rec = (await db.execute(select(UsageRecord).where(UsageRecord.kind == "inference"))).scalars().one()
    assert rec.outcome == "success" and rec.status_code == 200
    assert (rec.input_tokens, rec.output_tokens, rec.token_source) == (12, 2, "runtime_reported")
    assert rec.api_key_id == uuid.UUID(key["id"]) and rec.deployment_id == uuid.UUID(dep["id"])
    assert rec.request_id == resp.headers["x-agentmesh-request-id"]
    # Prompts and responses are never stored.
    stored = " ".join(str(getattr(rec, c.name)) for c in UsageRecord.__table__.columns)
    assert PROMPT not in stored and "Hel" not in stored

    usage = (await client.get(f"/api/v1/usage/{dep['id']}", headers=ready_deployment["customer"])).json()
    assert usage[0]["output_tokens"] == 2


async def test_user_jwt_also_works(client, ready_deployment):
    resp = await client.post(
        _url(ready_deployment["dep"]["id"]), json={"messages": []}, headers=ready_deployment["customer"]
    )
    assert resp.status_code == 200


async def test_gateway_auth_and_tenant_isolation(client, make_user, ready_deployment):
    dep_id = ready_deployment["dep"]["id"]
    assert (await client.post(_url(dep_id), json={})).status_code == 401
    bad = {"Authorization": "Bearer am_sk_notarealkey"}
    assert (await client.post(_url(dep_id), json={}, headers=bad)).status_code == 401

    _, mallory = await make_user("customer")
    mallory_key = await _key(client, mallory)
    resp = await client.post(_url(dep_id), json={}, headers={"Authorization": f"Bearer {mallory_key['key']}"})
    assert resp.status_code == 404  # other tenants cannot even confirm the deployment exists
    _, operator = await make_user("operator")
    assert (await client.post(_url(dep_id), json={}, headers=operator)).status_code == 404

    key = await _key(client, ready_deployment["customer"])
    await client.delete(f"/api/v1/api-keys/{key['id']}", headers=ready_deployment["customer"])
    assert (
        await client.post(_url(dep_id), json={}, headers={"Authorization": f"Bearer {key['key']}"})
    ).status_code == 401


async def test_deployment_scoped_key(client, ready_deployment, enroll_node, ollama_model):
    customer = ready_deployment["customer"]
    await enroll_node()
    other_dep = (
        await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)
    ).json()
    key = await _key(client, customer, deployment_id=ready_deployment["dep"]["id"])
    h = {"Authorization": f"Bearer {key['key']}"}
    assert (await client.post(_url(ready_deployment["dep"]["id"]), json={}, headers=h)).status_code == 200
    assert (await client.post(_url(other_dep["id"]), json={}, headers=h)).status_code == 404


async def test_unsupported_paths_and_bad_bodies(client, ready_deployment):
    dep_id, h = ready_deployment["dep"]["id"], ready_deployment["customer"]
    assert (await client.post(_url(dep_id, "api/pull"), json={"model": "x"}, headers=h)).status_code == 404
    assert (await client.post(_url(dep_id, "api/delete"), json={}, headers=h)).status_code == 404
    assert (await client.get(_url(dep_id, "api/ps"), headers=h)).status_code == 404
    resp = await client.post(_url(dep_id), content=b"not json", headers={**h, "content-type": "application/json"})
    assert resp.status_code == 400
    assert (await client.post(_url(dep_id), json=[1, 2], headers=h)).status_code == 400


async def test_request_size_limit(client, ready_deployment, monkeypatch):
    monkeypatch.setattr(settings, "GATEWAY_MAX_BODY_BYTES", 1000)
    resp = await client.post(
        _url(ready_deployment["dep"]["id"]), json={"prompt": "x" * 5000}, headers=ready_deployment["customer"]
    )
    assert resp.status_code == 413


async def test_rate_limit(client, ready_deployment, monkeypatch):
    monkeypatch.setattr(settings, "GATEWAY_RATE_LIMIT_PER_MINUTE", 2)
    h = ready_deployment["customer"]
    codes = [(await client.post(_url(ready_deployment["dep"]["id"]), json={}, headers=h)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_local_model_listing(client, ready_deployment):
    h = ready_deployment["customer"]
    tags = (await client.get(_url(ready_deployment["dep"]["id"], "api/tags"), headers=h)).json()
    assert [m["name"] for m in tags["models"]] == ["qwen2.5:0.5b"]
    models = (await client.get(_url(ready_deployment["dep"]["id"], "v1/models"), headers=h)).json()
    assert models["data"][0]["id"] == "qwen2.5:0.5b"


async def test_node_not_connected(client, db, ready_deployment):
    broker.unregister(ready_deployment["worker"].conn)
    resp = await client.post(_url(ready_deployment["dep"]["id"]), json={}, headers=ready_deployment["customer"])
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "node_unavailable"
    rec = (await db.execute(select(UsageRecord))).scalars().one()
    assert rec.outcome == "node_unavailable" and rec.input_tokens is None


async def test_runtime_error_midstream_is_not_counted_as_success(client, db, ready_deployment):
    ready_deployment["worker"].mode = "error_midstream"
    resp = await client.post(_url(ready_deployment["dep"]["id"]), json={}, headers=ready_deployment["customer"])
    assert resp.status_code == 200  # headers were already sent; body is truncated
    rec = (await db.execute(select(UsageRecord))).scalars().one()
    assert rec.outcome == "runtime_error"
    assert rec.input_tokens is None and rec.output_tokens is None  # never estimated


async def test_first_byte_timeout(client, db, ready_deployment, monkeypatch):
    monkeypatch.setattr(settings, "GATEWAY_FIRST_BYTE_TIMEOUT_SECONDS", 0.2)
    ready_deployment["worker"].mode = "silent"
    resp = await client.post(_url(ready_deployment["dep"]["id"]), json={}, headers=ready_deployment["customer"])
    assert resp.status_code == 504
    assert ready_deployment["worker"].cancelled  # the worker was told to abandon the request
    rec = (await db.execute(select(UsageRecord))).scalars().one()
    assert rec.outcome == "timeout"


async def test_unhealthy_deployment_rejected(client, db, ready_deployment):
    node = ready_deployment["node"]
    await client.post(
        "/api/v1/worker/heartbeat", json={"worker_version": "t", "deployments": []}, headers=node["headers"]
    )
    resp = await client.post(_url(ready_deployment["dep"]["id"]), json={}, headers=ready_deployment["customer"])
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "deployment_unhealthy"


# --- worker-side tunnel handler ------------------------------------------------------------------------


async def test_worker_tunnel_rejects_disallowed_requests():
    sent = []

    async def send(frame):
        sent.append(frame)

    allowed = frozenset({"/api/chat", "/v1/chat/completions"})
    handler = TunnelHandler(lambda dep: ("http://127.0.0.1:1", "qwen2.5:0.5b", allowed) if dep == "d1" else None, 2, 5)
    await handler.on_frame(
        {"type": "request", "id": "r1", "deployment_id": "d1", "method": "POST", "path": "/api/pull", "body": {}}, send
    )
    await handler.on_frame(
        {"type": "request", "id": "r2", "deployment_id": "zz", "method": "POST", "path": "/api/chat", "body": {}}, send
    )
    await asyncio.sleep(0.05)
    codes = {f["id"]: f.get("code") for f in sent}
    assert codes == {"r1": "rejected", "r2": "deployment_not_running"}
