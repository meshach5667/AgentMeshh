"""Scheduler, reservations, deployment lifecycle, and background reconciliation."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.background import monitors
from app.core.config import settings
from app.core.timeutil import utcnow
from app.models import ApiKey, Deployment, Model, Node, NodeCommand, ResourceReservation
from app.models.deployment import DeploymentStatus as S
from app.services import deployment_lifecycle as lifecycle
from app.services.deployment_lifecycle import TRANSITIONS
from tests.conftest import TEST_DATABASE_URL


async def _deploy(client, headers, model, **body):
    return await client.post("/api/v1/deployments", json={"model_id": str(model.id), **body}, headers=headers)


async def _node(db, node_id) -> Node:
    node = await db.get(Node, uuid.UUID(str(node_id)))
    await db.refresh(node)
    return node


async def _dep(db, dep_id) -> Deployment:
    dep = await db.get(Deployment, uuid.UUID(str(dep_id)))
    await db.refresh(dep)
    return dep


async def _report(client, node, dep_id, state, **extra):
    return await client.post(
        f"/api/v1/worker/deployments/{dep_id}/status", json={"state": state, **extra}, headers=node["headers"]
    )


def test_state_machine_terminal_states_have_no_exits():
    for state in (S.STOPPED, S.FAILED, S.CANCELLED):
        assert TRANSITIONS[state] == frozenset()
    assert S.READY not in TRANSITIONS[S.REQUESTED]  # cannot skip scheduling
    assert all(S.FAILED in TRANSITIONS[s] for s in lifecycle.ACTIVE if s != S.FAILED)


async def test_happy_path_reserves_runs_and_releases(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node(cpu=4, ram_mb=4096, disk_mb=10000)
    _, customer = await make_user("customer")

    resp = await _deploy(client, customer, ollama_model)
    assert resp.status_code == 201, resp.text
    dep = resp.json()
    assert dep["status"] == "SCHEDULED" and dep["endpoint"] is None
    n = await _node(db, node["node_id"])
    assert (n.reserved_cpu_cores, n.reserved_ram_mb, n.reserved_disk_mb) == (1, 1024, 768)

    for state in ("PROVISIONING", "STARTING"):
        assert (await _report(client, node, dep["id"], state)).status_code == 200
    # Gateway refuses until READY.
    assert (
        await client.post(f"/api/v1/deployments/{dep['id']}/ollama/api/chat", json={}, headers=customer)
    ).status_code == 409
    assert (await _report(client, node, dep["id"], "READY", model_digest="sha256:abc")).status_code == 200

    got = (await client.get(f"/api/v1/deployments/{dep['id']}", headers=customer)).json()
    assert got["status"] == "READY"
    assert got["endpoint"].endswith(f"/api/v1/deployments/{dep['id']}/ollama")
    assert got["model_digest"] == "sha256:abc"

    stop = await client.post(f"/api/v1/deployments/{dep['id']}/stop", headers=customer)
    assert stop.json()["status"] == "STOPPING"
    cmds = (await client.post("/api/v1/worker/commands/poll", json={"wait_seconds": 0}, headers=node["headers"])).json()
    assert [c["type"] for c in cmds["commands"]] == ["DEPLOY", "STOP"]

    assert (await _report(client, node, dep["id"], "STOPPED")).status_code == 200
    final = await _dep(db, dep["id"])
    assert final.status == "STOPPED" and final.cleanup_status == "done"
    n = await _node(db, node["node_id"])
    assert (n.reserved_cpu_cores, n.reserved_ram_mb, n.reserved_disk_mb) == (0, 0, 0)

    events = (await client.get(f"/api/v1/deployments/{dep['id']}/events", headers=customer)).json()
    path = [e["to_status"] for e in events if e["to_status"]]
    assert path == ["REQUESTED", "SCHEDULED", "PROVISIONING", "STARTING", "READY", "STOPPING", "STOPPED"]


async def test_duplicate_stopped_reports_release_once(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await _report(client, node, dep["id"], "READY")
    await client.post(f"/api/v1/deployments/{dep['id']}/stop", headers=customer)
    for _ in range(3):
        assert (await _report(client, node, dep["id"], "STOPPED")).status_code == 200
    n = await _node(db, node["node_id"])
    assert n.reserved_ram_mb == 0  # never negative


async def test_stop_before_delivery_cancels_without_node(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    resp = await client.post(f"/api/v1/deployments/{dep['id']}/stop", headers=customer)
    assert resp.json()["status"] == "CANCELLED"
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 0
    cmds = (await client.post("/api/v1/worker/commands/poll", json={"wait_seconds": 0}, headers=node["headers"])).json()
    assert cmds["commands"] == []


async def test_cancel_during_provisioning_ends_cancelled(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await client.post("/api/v1/worker/commands/poll", json={"wait_seconds": 0}, headers=node["headers"])
    await _report(client, node, dep["id"], "PROVISIONING", message="Downloading model: 40%")
    await client.post(f"/api/v1/deployments/{dep['id']}/stop", headers=customer)
    # Late progress from the worker is ignored, not applied.
    late = await _report(client, node, dep["id"], "READY")
    assert late.json().get("ignored") is True
    await _report(client, node, dep["id"], "STOPPED")
    assert (await _dep(db, dep["id"])).status == "CANCELLED"


async def test_worker_failure_releases_and_records_error(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    resp = await _report(
        client, node, dep["id"], "FAILED", error_code="MODEL_PULL_FAILED", message="manifest not found"
    )
    assert resp.status_code == 200
    got = (await client.get(f"/api/v1/deployments/{dep['id']}", headers=customer)).json()
    assert got["status"] == "FAILED" and got["error_code"] == "MODEL_PULL_FAILED"
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 0


async def test_invalid_transition_rejected(client, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await _report(client, node, dep["id"], "READY")
    assert (await _report(client, node, dep["id"], "PROVISIONING")).status_code == 409


@pytest.mark.parametrize(
    "node_kwargs,reason",
    [
        ({"cpu": 4, "ram_mb": 512}, "insufficient_capacity"),
        ({"runtimes": []}, "unsupported_runtime"),
    ],
)
async def test_no_eligible_node_reasons(client, make_user, enroll_node, ollama_model, node_kwargs, reason):
    await enroll_node(**node_kwargs)
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, ollama_model)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["code"] == "no_eligible_node"
    assert detail["reasons"] == {reason: 1}


async def test_gpu_requirement_and_paused_and_stale_nodes(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, ollama_model, config={"require_gpu": True})
    assert resp.json()["detail"]["reasons"] == {"incompatible_hardware": 1}

    paused = await client.patch(
        f"/api/v1/nodes/{node['node_id']}", json={"accepting_workloads": False}, headers=node["provider_headers"]
    )
    assert paused.status_code == 200
    assert (await _deploy(client, customer, ollama_model)).json()["detail"]["reasons"] == {"provider_unavailable": 1}
    await client.patch(
        f"/api/v1/nodes/{node['node_id']}", json={"accepting_workloads": True}, headers=node["provider_headers"]
    )

    n = await _node(db, node["node_id"])
    n.last_heartbeat = utcnow() - timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS + 5)
    await db.commit()
    assert (await _deploy(client, customer, ollama_model)).json()["detail"]["reasons"] == {"provider_unavailable": 1}


async def test_no_nodes_at_all(client, make_user, ollama_model):
    _, customer = await make_user("customer")
    resp = await _deploy(client, customer, ollama_model)
    assert resp.status_code == 503
    assert "No compute nodes" in resp.json()["detail"]["message"]


@pytest.mark.parametrize("config", [{"num_ctx": 999999}, {"docker_args": "--privileged"}, {"num_ctx": "big"}])
async def test_invalid_deployment_config_rejected(client, make_user, enroll_node, ollama_model, config):
    await enroll_node()
    _, customer = await make_user("customer")
    assert (await _deploy(client, customer, ollama_model, config=config)).status_code == 422


async def test_unsupported_runtime_and_missing_requirements(client, db, make_user, enroll_node):
    await enroll_node()
    _, customer = await make_user("customer")
    vllm = Model(name="x", runtime="vllm", model_tag="org/x", min_ram_mb=1, min_disk_mb=1, is_approved=True)
    bare = Model(name="y", runtime="ollama", model_tag="tiny:1b", is_approved=True)
    evil = Model(name="z", runtime="ollama", model_tag="x; curl evil", min_ram_mb=1, min_disk_mb=1, is_approved=True)
    db.add_all([vllm, bare, evil])
    await db.commit()
    for model in (vllm, bare, evil):
        resp = await _deploy(client, customer, model)
        assert resp.status_code == 422, resp.text


async def test_reservation_rejects_stale_capacity_read(db, enroll_node, ollama_model):
    """Two schedulers both see free capacity (stale read); only the first conditional UPDATE may win."""
    from app.services.catalog_service import DeploymentConfig, estimate_requirements
    from app.services.scheduler_service import evaluate_nodes, try_reserve

    node = await enroll_node(cpu=8, ram_mb=1024, disk_mb=10000)  # room for exactly one
    req = estimate_requirements(ollama_model, DeploymentConfig())
    seen_by_a = (await evaluate_nodes(db, req)).eligible
    seen_by_b = (await evaluate_nodes(db, req)).eligible
    assert seen_by_a and seen_by_b  # both think the node is free

    dep_a, dep_b = (Deployment(id=uuid.uuid4(), status="REQUESTED", config={}) for _ in range(2))
    db.add_all([dep_a, dep_b])
    await db.flush()
    assert await try_reserve(db, seen_by_a[0], dep_a.id, req) is True
    assert await try_reserve(db, seen_by_b[0], dep_b.id, req) is False
    await db.commit()
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 1024


@pytest.mark.skipif("sqlite" in TEST_DATABASE_URL, reason="needs a database with real concurrent connections")
async def test_capacity_is_never_oversubscribed(client, db, make_user, enroll_node, ollama_model):
    """The node has room for exactly two deployments; five concurrent requests must yield exactly two."""
    node = await enroll_node(cpu=8, ram_mb=2048, disk_mb=10000)
    _, customer = await make_user("customer")
    results = await asyncio.gather(*[_deploy(client, customer, ollama_model) for _ in range(5)])
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 201, 503, 503, 503]
    n = await _node(db, node["node_id"])
    assert n.reserved_ram_mb == 2048
    active = (
        (await db.execute(select(ResourceReservation).where(ResourceReservation.status == "ACTIVE"))).scalars().all()
    )
    assert len(active) == 2


async def test_idempotency_key_returns_same_deployment(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    a = await _deploy(client, customer, ollama_model, idempotency_key="retry-1")
    b = await _deploy(client, customer, ollama_model, idempotency_key="retry-1")
    assert a.json()["id"] == b.json()["id"]
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 1024  # reserved once


async def test_delete_revokes_scoped_keys_and_hides_deployment(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await _report(client, node, dep["id"], "READY")
    key = (
        await client.post("/api/v1/api-keys", json={"name": "k", "deployment_id": dep["id"]}, headers=customer)
    ).json()

    resp = await client.delete(f"/api/v1/deployments/{dep['id']}", headers=customer)
    assert resp.status_code == 200 and resp.json()["status"] == "STOPPING"
    assert (await client.get(f"/api/v1/deployments/{dep['id']}", headers=customer)).status_code == 404
    assert dep["id"] not in [d["id"] for d in (await client.get("/api/v1/deployments", headers=customer)).json()]
    row = await db.get(ApiKey, uuid.UUID(key["id"]))
    await db.refresh(row)
    assert row.revoked_at is not None
    # Worker still confirms cleanup, which releases capacity.
    await _report(client, node, dep["id"], "STOPPED")
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 0


async def test_stale_node_monitor_marks_offline_and_unhealthy(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await _report(client, node, dep["id"], "READY")

    future = utcnow() + timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS + 1)
    assert await monitors.run_stale_nodes(now=future) == 1
    assert (await _node(db, node["node_id"])).status == "OFFLINE"
    assert (await _dep(db, dep["id"])).status == "UNHEALTHY"
    # Capacity stays reserved during a disconnection so the node is not double-booked.
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 1024

    # Worker comes back and reports the workload healthy -> READY again.
    hb = await client.post(
        "/api/v1/worker/heartbeat",
        json={
            "worker_version": "t",
            "deployments": [{"deployment_id": dep["id"], "state": "running", "healthy": True}],
        },
        headers=node["headers"],
    )
    assert hb.json()["stop_deployments"] == []
    assert (await _dep(db, dep["id"])).status == "READY"
    assert (await _node(db, node["node_id"])).status == "ONLINE"


async def test_heartbeat_without_workload_marks_unhealthy(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await _report(client, node, dep["id"], "READY")
    await client.post(
        "/api/v1/worker/heartbeat", json={"worker_version": "t", "deployments": []}, headers=node["headers"]
    )
    assert (await _dep(db, dep["id"])).status == "UNHEALTHY"


async def test_provisioning_stall_fails_and_cleans_up(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await client.post("/api/v1/worker/commands/poll", json={"wait_seconds": 0}, headers=node["headers"])
    await _report(client, node, dep["id"], "PROVISIONING")
    future = utcnow() + timedelta(seconds=settings.PROVISION_STALL_TIMEOUT_SECONDS + 1)
    assert await monitors.run_deployment_timeouts(now=future) == 1
    got = await _dep(db, dep["id"])
    assert got.status == "FAILED" and got.error_code == "PROVISION_STALLED"
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 0
    stops = (await db.execute(select(NodeCommand).where(NodeCommand.type == "STOP"))).scalars().all()
    assert len(stops) == 1


async def test_unconfirmed_stop_times_out_to_pending_node_cleanup(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await _report(client, node, dep["id"], "READY")
    await client.post(f"/api/v1/deployments/{dep['id']}/stop", headers=customer)
    future = utcnow() + timedelta(seconds=settings.STOP_TIMEOUT_SECONDS + 1)
    await monitors.run_deployment_timeouts(now=future)
    got = await _dep(db, dep["id"])
    assert got.status == "STOPPED" and got.cleanup_status == "pending_node"
    # When the node returns still running it, it is told to stop.
    hb = await client.post(
        "/api/v1/worker/heartbeat",
        json={
            "worker_version": "t",
            "deployments": [{"deployment_id": dep["id"], "state": "running", "healthy": True}],
        },
        headers=node["headers"],
    )
    assert hb.json()["stop_deployments"] == [dep["id"]]


async def test_undelivered_deploy_fails_after_max_attempts(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    cmd = (await db.execute(select(NodeCommand))).scalars().one()
    cmd.status, cmd.attempts = "LEASED", cmd.max_attempts
    cmd.lease_expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    assert await monitors.run_command_leases() == 1
    got = await _dep(db, dep["id"])
    assert got.status == "FAILED" and got.error_code == "NODE_UNRESPONSIVE"
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 0


async def test_revoking_node_fails_its_deployments(client, db, make_user, enroll_node, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = (await _deploy(client, customer, ollama_model)).json()
    await _report(client, node, dep["id"], "READY")
    await client.post(f"/api/v1/nodes/{node['node_id']}/revoke", headers=node["provider_headers"])
    got = await _dep(db, dep["id"])
    assert got.status == "FAILED" and got.error_code == "NODE_REVOKED"  # no other node to move to
    assert (await _node(db, node["node_id"])).reserved_ram_mb == 0
