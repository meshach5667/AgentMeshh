"""Phase 3: moving deployments off failed nodes, restarts, and related regressions."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.background import monitors
from app.core.config import settings
from app.core.timeutil import utcnow
from app.models import Deployment, Node, NodeCommand, ResourceReservation


async def _deploy(client, headers, model):
    resp = await client.post("/api/v1/deployments", json={"model_id": str(model.id)}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _report(client, node, dep_id, state, **extra):
    return await client.post(
        f"/api/v1/worker/deployments/{dep_id}/status", json={"state": state, **extra}, headers=node["headers"]
    )


async def _poll(client, node):
    resp = await client.post("/api/v1/worker/commands/poll", json={"wait_seconds": 0}, headers=node["headers"])
    return resp.json()["commands"]


async def _dep(db, dep_id) -> Deployment:
    dep = await db.get(Deployment, uuid.UUID(str(dep_id)))
    await db.refresh(dep)
    return dep


async def _reserved(db, node) -> int:
    n = await db.get(Node, uuid.UUID(node["node_id"]))
    await db.refresh(n)
    return n.reserved_ram_mb


@pytest.fixture
async def two_nodes(enroll_node, make_user):
    _, provider = await make_user("provider")
    a = await enroll_node(provider=provider, ram_mb=8192)
    b = await enroll_node(provider=provider, ram_mb=4096)  # less free RAM, so A is preferred first
    return a, b


async def test_worker_resource_failure_moves_to_another_node(client, db, make_user, two_nodes, ollama_model):
    a, b = two_nodes
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    assert dep["node_id"] == a["node_id"]
    await _poll(client, a)
    resp = await _report(client, a, dep["id"], "FAILED", error_code="INSUFFICIENT_MEMORY", message="Only 100 MB free")
    assert resp.json()["status"] == "SCHEDULED"

    moved = await _dep(db, dep["id"])
    assert str(moved.node_id) == b["node_id"] and moved.schedule_attempts == 2
    assert a["node_id"] in moved.excluded_node_ids
    assert await _reserved(db, a) == 0 and await _reserved(db, b) == 1024
    assert [c["type"] for c in await _poll(client, b)] == ["DEPLOY"]

    # Late reports from the old node are rejected; it no longer owns the deployment.
    assert (await _report(client, a, dep["id"], "READY")).status_code == 404
    # The new node completes it; same id and endpoint path for the customer.
    assert (await _report(client, b, dep["id"], "READY")).status_code == 200
    got = (await client.get(f"/api/v1/deployments/{dep['id']}", headers=customer)).json()
    assert got["status"] == "READY" and got["endpoint"].endswith(f"/deployments/{dep['id']}/ollama")

    active = (
        (await db.execute(select(ResourceReservation).where(ResourceReservation.status == "ACTIVE"))).scalars().all()
    )
    assert len(active) == 1  # history row for node A is RELEASED


async def test_model_failures_are_not_moved(client, db, make_user, two_nodes, ollama_model):
    a, _ = two_nodes
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _poll(client, a)
    resp = await _report(client, a, dep["id"], "FAILED", error_code="HEALTHCHECK_FAILED", message="no answer")
    assert resp.json()["status"] == "FAILED"
    assert (await _dep(db, dep["id"])).schedule_attempts == 1


async def test_no_other_node_means_failed_with_explanation(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _poll(client, node)
    await _report(client, node, dep["id"], "FAILED", error_code="INSUFFICIENT_DISK", message="disk full")
    got = await _dep(db, dep["id"])
    assert got.status == "FAILED" and got.error_code == "INSUFFICIENT_DISK"
    assert "already failed this deployment" in got.error_message
    assert await _reserved(db, node) == 0


async def test_placements_are_bounded(client, db, make_user, enroll_node, ollama_model, monkeypatch):
    monkeypatch.setattr(settings, "MAX_SCHEDULE_ATTEMPTS", 2)
    _, provider = await make_user("provider")
    nodes = [await enroll_node(provider=provider) for _ in range(3)]
    by_id = {n["node_id"]: n for n in nodes}
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    first = by_id[dep["node_id"]]
    await _report(client, first, dep["id"], "FAILED", error_code="RUNTIME_START_FAILED")
    second = by_id[str((await _dep(db, dep["id"])).node_id)]
    assert second is not first
    await _report(client, second, dep["id"], "FAILED", error_code="RUNTIME_START_FAILED")
    got = await _dep(db, dep["id"])
    assert got.status == "FAILED" and got.schedule_attempts == 2  # third node never tried


async def test_offline_node_moves_provisioning_deployments_immediately(client, db, make_user, two_nodes, ollama_model):
    a, b = two_nodes
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _poll(client, a)
    await _report(client, a, dep["id"], "PROVISIONING")
    # B keeps heartbeating; A goes silent.
    future = utcnow() + timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS + 1)
    n_b = await db.get(Node, uuid.UUID(b["node_id"]))
    n_b.last_heartbeat = future
    await db.commit()
    assert await monitors.run_stale_nodes(now=future) == 1
    got = await _dep(db, dep["id"])
    assert str(got.node_id) == b["node_id"] and got.status == "SCHEDULED"
    # A gets a STOP to clean up whatever it started, if it ever returns.
    stops = (await db.execute(select(NodeCommand).where(NodeCommand.type == "STOP"))).scalars().all()
    assert [str(c.node_id) for c in stops] == [a["node_id"]]


async def test_unhealthy_serving_deployment_moves_after_grace(client, db, make_user, two_nodes, ollama_model):
    a, b = two_nodes
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _report(client, a, dep["id"], "READY")
    future = utcnow() + timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS + 1)
    n_b = await db.get(Node, uuid.UUID(b["node_id"]))
    n_b.last_heartbeat = future + timedelta(seconds=settings.UNHEALTHY_GRACE_SECONDS + 1)
    await db.commit()
    await monitors.run_stale_nodes(now=future)
    assert (await _dep(db, dep["id"])).status == "UNHEALTHY"
    # Within the grace period nothing moves, and A's capacity stays reserved.
    await monitors.run_deployment_timeouts(now=future)
    assert (await _dep(db, dep["id"])).status == "UNHEALTHY" and await _reserved(db, a) == 1024

    later = future + timedelta(seconds=settings.UNHEALTHY_GRACE_SECONDS + 1)
    await monitors.run_deployment_timeouts(now=later)
    got = await _dep(db, dep["id"])
    assert got.status == "SCHEDULED" and str(got.node_id) == b["node_id"]
    assert await _reserved(db, a) == 0


async def test_graceful_disconnect_moves_provisioning_work(client, db, make_user, two_nodes, ollama_model):
    a, b = two_nodes
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _poll(client, a)
    await client.post("/api/v1/worker/disconnect", json={}, headers=a["headers"])
    got = await _dep(db, dep["id"])
    assert str(got.node_id) == b["node_id"]


async def test_revoked_node_work_moves(client, db, make_user, two_nodes, ollama_model):
    a, b = two_nodes
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _report(client, a, dep["id"], "READY")
    await client.post(f"/api/v1/nodes/{a['node_id']}/revoke", headers=a["provider_headers"])
    got = await _dep(db, dep["id"])
    assert got.status == "SCHEDULED" and str(got.node_id) == b["node_id"]
    events = (await client.get(f"/api/v1/deployments/{dep['id']}/events", headers=customer)).json()
    assert [e["to_status"] for e in events if e["to_status"]][-3:] == ["READY", "UNHEALTHY", "SCHEDULED"]


async def test_restart(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    assert (await client.post(f"/api/v1/deployments/{dep['id']}/restart", headers=customer)).status_code == 409
    await _poll(client, node)
    await _report(client, node, dep["id"], "READY")

    _, other = await make_user("customer")
    assert (await client.post(f"/api/v1/deployments/{dep['id']}/restart", headers=other)).status_code == 404
    resp = await client.post(f"/api/v1/deployments/{dep['id']}/restart", headers=customer)
    assert resp.status_code == 200 and resp.json()["status"] == "PROVISIONING"
    cmds = await _poll(client, node)
    assert [c["type"] for c in cmds] == ["RESTART"]
    assert cmds[0]["payload"]["model_tag"] == "qwen2.5:0.5b"
    assert await _reserved(db, {"node_id": node["node_id"]}) == 1024  # capacity kept across restart
    # Gateway refuses while restarting.
    assert (
        await client.post(f"/api/v1/deployments/{dep['id']}/ollama/api/chat", json={}, headers=customer)
    ).status_code == 409
    await _report(client, node, dep["id"], "STARTING")
    await _report(client, node, dep["id"], "READY")
    got = await _dep(db, dep["id"])
    assert got.status == "READY" and got.restart_count == 1


async def test_restart_refused_when_node_offline(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _report(client, node, dep["id"], "READY")
    await client.post("/api/v1/worker/disconnect", json={}, headers=node["headers"])
    resp = await client.post(f"/api/v1/deployments/{dep['id']}/restart", headers=customer)
    assert resp.status_code == 409 and "offline" in resp.json()["detail"]


async def test_stale_worker_cannot_regress_ready_deployment(client, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await _report(client, node, dep["id"], "READY")
    assert (await _report(client, node, dep["id"], "STARTING")).status_code == 409


async def test_marketplace_lists_real_nodes(client, enroll_node):
    """Regression: the marketplace called .value on a plain string status and crashed with any node."""
    await enroll_node()
    resp = await client.get("/api/v1/marketplace/nodes")
    assert resp.status_code == 200 and resp.json()[0]["status"] == "ONLINE"
