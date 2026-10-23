"""Phase 4 control-plane behaviour: worker-reported availability, drain, whoami, and release serving."""

import uuid

import pytest

from app.core.config import settings
from app.models import Deployment


async def _deploy(client, headers, model):
    return await client.post("/api/v1/deployments", json={"model_id": str(model.id)}, headers=headers)


async def test_locally_paused_worker_gets_no_new_work(client, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    hb = {"worker_version": "t", "available": False, "unavailable_reason": "schedule"}
    await client.post("/api/v1/worker/heartbeat", json=hb, headers=node["headers"])
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, ollama_model)
    assert resp.status_code == 503 and resp.json()["detail"]["reasons"] == {"provider_unavailable": 1}
    shown = (await client.get(f"/api/v1/nodes/{node['node_id']}", headers=node["provider_headers"])).json()
    assert shown["worker_available"] is False and shown["worker_unavailable_reason"] == "schedule"

    await client.post("/api/v1/worker/heartbeat", json={"worker_version": "t"}, headers=node["headers"])
    assert (await _deploy(client, customer, ollama_model)).status_code == 201


async def test_drained_workload_moves_to_another_node(client, db, make_user, enroll_node, ollama_model):
    _, provider = await make_user("provider")
    a = await enroll_node(provider=provider, ram_mb=8192)
    b = await enroll_node(provider=provider, ram_mb=4096)
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await client.post(f"/api/v1/worker/deployments/{dep['id']}/status", json={"state": "READY"}, headers=a["headers"])
    resp = await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status",
        json={"state": "STOPPED", "error_code": "NODE_UNAVAILABLE", "message": "Provider drained the node"},
        headers=a["headers"],
    )
    assert resp.json()["status"] == "SCHEDULED"
    moved = await db.get(Deployment, uuid.UUID(dep["id"]))
    await db.refresh(moved)
    assert str(moved.node_id) == b["node_id"]


async def test_whoami_is_read_only_and_authenticated(client, enroll_node):
    node = await enroll_node()
    assert (await client.get("/api/v1/worker/whoami")).status_code == 401
    me = (await client.get("/api/v1/worker/whoami", headers=node["headers"])).json()
    assert me["node_id"] == node["node_id"] and me["status"] == "ONLINE"


@pytest.fixture
def release_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKER_RELEASE_DIR", str(tmp_path))
    wheel = tmp_path / "agentmesh_worker-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    (tmp_path / "manifest.json").write_text('{"version": "9.9.9"}')
    (tmp_path / "manifest.sig").write_text("c2ln\n")
    (tmp_path.parent / "secret.txt").write_text("do not serve")
    return tmp_path


async def test_release_endpoints(client, enroll_node, release_dir):
    node = await enroll_node()
    h = node["headers"]
    assert (await client.get("/api/v1/worker/releases/latest")).status_code == 401
    latest = (await client.get("/api/v1/worker/releases/latest", headers=h)).json()
    assert latest == {"manifest": '{"version": "9.9.9"}', "signature": "c2ln"}
    ok = await client.get("/api/v1/worker/releases/files/agentmesh_worker-9.9.9-py3-none-any.whl", headers=h)
    assert ok.status_code == 200 and ok.content == b"wheel"
    for bad in ("..%2Fsecret.txt", "manifest.json", "agentmesh_worker-1.0.0-py3-none-any.whl"):
        assert (await client.get(f"/api/v1/worker/releases/files/{bad}", headers=h)).status_code == 404
    hb = await client.post("/api/v1/worker/heartbeat", json={"worker_version": "t"}, headers=h)
    assert hb.json()["latest_worker_version"] == "9.9.9"


async def test_no_release_published(client, enroll_node):
    node = await enroll_node()
    assert (await client.get("/api/v1/worker/releases/latest", headers=node["headers"])).status_code == 404
