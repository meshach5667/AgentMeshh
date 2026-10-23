"""Worker protocol v1: enrollment, authentication, heartbeats, command queue, status reports."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.timeutil import utcnow
from app.models import Node, NodeCommand, NodeEnrollmentToken
from tests.conftest import HARDWARE


async def _token(client, provider_headers):
    resp = await client.post("/api/v1/nodes/enrollment-tokens", json={}, headers=provider_headers)
    assert resp.status_code == 201
    return resp.json()["token"]


def _enroll_body(token, **over):
    body = {
        "token": token,
        "name": "n",
        "mode": "agent",
        "worker_version": "t",
        "protocol_version": 1,
        "hardware": HARDWARE,
        "allocation": {"cpu_cores": 2, "ram_mb": 2048, "disk_mb": 5000, "vram_mb": 0},
        "runtimes": [{"name": "ollama", "version": "1", "backend": "process", "available": True}],
    }
    body.update(over)
    return body


async def test_enrollment_token_requires_provider(client, make_user):
    _, customer = await make_user("customer")
    assert (await client.post("/api/v1/nodes/enrollment-tokens", json={}, headers=customer)).status_code == 403
    assert (await client.post("/api/v1/nodes/enrollment-tokens", json={})).status_code == 401


async def test_enrollment_token_is_single_use(client, make_user):
    _, provider = await make_user("provider")
    token = await _token(client, provider)
    assert (await client.post("/api/v1/worker/enroll", json=_enroll_body(token))).status_code == 200
    assert (await client.post("/api/v1/worker/enroll", json=_enroll_body(token))).status_code == 401


async def test_expired_or_unknown_token_rejected(client, db, make_user):
    _, provider = await make_user("provider")
    token = await _token(client, provider)
    row = (await db.execute(select(NodeEnrollmentToken))).scalars().one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    assert (await client.post("/api/v1/worker/enroll", json=_enroll_body(token))).status_code == 401
    bogus = "am_enroll_" + "x" * 40
    assert (await client.post("/api/v1/worker/enroll", json=_enroll_body(bogus))).status_code == 401


async def test_enroll_rejects_unknown_protocol_and_fields(client, make_user):
    _, provider = await make_user("provider")
    token = await _token(client, provider)
    assert (
        await client.post("/api/v1/worker/enroll", json=_enroll_body(token, protocol_version=99))
    ).status_code == 426
    token = await _token(client, provider)
    resp = await client.post("/api/v1/worker/enroll", json=_enroll_body(token, run_shell="rm -rf /"))
    assert resp.status_code == 422


async def test_allocation_is_clamped_to_reported_hardware(client, db, enroll_node):
    node = await enroll_node(cpu=999, ram_mb=10**7, disk_mb=10**8)
    row = await db.get(Node, uuid.UUID(node["node_id"]))
    assert row.allocated_cpu_cores == HARDWARE["cpu_cores"]
    assert row.allocated_ram_mb == HARDWARE["ram_mb"]
    assert row.allocated_disk_mb == HARDWARE["disk_free_mb"]
    assert row.api_key_hash.startswith("sha256$")
    assert node["credential"] not in row.api_key_hash


async def test_worker_auth(client, enroll_node):
    node = await enroll_node()
    other = await enroll_node()
    hb = {"worker_version": "t"}
    assert (await client.post("/api/v1/worker/heartbeat", json=hb, headers=node["headers"])).status_code == 200
    # Credential of another node
    crossed = {**node["headers"], "Authorization": other["headers"]["Authorization"]}
    assert (await client.post("/api/v1/worker/heartbeat", json=hb, headers=crossed)).status_code == 401
    assert (await client.post("/api/v1/worker/heartbeat", json=hb)).status_code == 401
    bad_proto = {**node["headers"], "X-AgentMesh-Protocol": "7"}
    assert (await client.post("/api/v1/worker/heartbeat", json=hb, headers=bad_proto)).status_code == 426


async def test_heartbeat_allocation_requires_hardware(client, enroll_node):
    node = await enroll_node()
    body = {"worker_version": "t", "allocation": {"cpu_cores": 1, "ram_mb": 1, "disk_mb": 1}}
    assert (await client.post("/api/v1/worker/heartbeat", json=body, headers=node["headers"])).status_code == 422


async def test_heartbeat_tells_worker_to_stop_unknown_workloads(client, enroll_node):
    node = await enroll_node()
    stray = str(uuid.uuid4())
    resp = await client.post(
        "/api/v1/worker/heartbeat",
        json={"worker_version": "t", "deployments": [{"deployment_id": stray, "state": "running", "healthy": True}]},
        headers=node["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["stop_deployments"] == [stray]


async def test_revoked_node_cannot_authenticate(client, enroll_node, make_user):
    node = await enroll_node()
    _, stranger = await make_user("provider")
    assert (await client.post(f"/api/v1/nodes/{node['node_id']}/revoke", headers=stranger)).status_code == 404
    resp = await client.post(f"/api/v1/nodes/{node['node_id']}/revoke", headers=node["provider_headers"])
    assert resp.status_code == 200 and resp.json()["status"] == "REVOKED"
    hb = await client.post("/api/v1/worker/heartbeat", json={"worker_version": "t"}, headers=node["headers"])
    assert hb.status_code == 401


async def test_poll_leases_once_and_redelivers_after_lease_expiry(client, db, enroll_node, make_user, ollama_model):
    node = await enroll_node()
    _, customer = await make_user("customer")
    dep = await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)
    assert dep.status_code == 201, dep.text

    poll = {"wait_seconds": 0}
    first = (await client.post("/api/v1/worker/commands/poll", json=poll, headers=node["headers"])).json()["commands"]
    assert [c["type"] for c in first] == ["DEPLOY"]
    assert first[0]["payload"]["model_tag"] == "qwen2.5:0.5b"
    again = (await client.post("/api/v1/worker/commands/poll", json=poll, headers=node["headers"])).json()["commands"]
    assert again == []  # leased, not redelivered while the lease is valid

    cmd = await db.get(NodeCommand, uuid.UUID(first[0]["id"]))
    cmd.lease_expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    redelivered = (await client.post("/api/v1/worker/commands/poll", json=poll, headers=node["headers"])).json()
    assert redelivered["commands"][0]["id"] == first[0]["id"]
    assert redelivered["commands"][0]["attempt"] == 2

    ack = f"/api/v1/worker/commands/{first[0]['id']}/ack"
    assert (await client.post(ack, json={"status": "accepted"}, headers=node["headers"])).status_code == 200
    assert (
        await client.post(ack, json={"status": "accepted"}, headers=node["headers"])
    ).status_code == 200  # idempotent


async def test_commands_are_scoped_to_their_node(client, enroll_node, make_user, ollama_model):
    node = await enroll_node()
    await client.post(
        "/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=(await make_user("customer"))[1]
    )
    other = await enroll_node(cpu=0)  # no capacity, so never scheduled
    cmds = (await client.post("/api/v1/worker/commands/poll", json={"wait_seconds": 0}, headers=node["headers"])).json()
    stolen = await client.post(
        f"/api/v1/worker/commands/{cmds['commands'][0]['id']}/ack", json={"status": "failed"}, headers=other["headers"]
    )
    assert stolen.status_code == 404


async def test_status_report_from_wrong_node_rejected(client, enroll_node, make_user, ollama_model):
    node = await enroll_node()
    other = await enroll_node(cpu=0)
    _, customer = await make_user("customer")
    dep = (await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)).json()
    url = f"/api/v1/worker/deployments/{dep['id']}/status"
    assert (await client.post(url, json={"state": "READY"}, headers=other["headers"])).status_code == 404
    assert (await client.post(url, json={"state": "PROVISIONING"}, headers=node["headers"])).status_code == 200


async def test_worker_body_size_limit(client, enroll_node):
    node = await enroll_node()
    huge = {"worker_version": "t", "metrics": {f"m{i}": 1.0 for i in range(10)}, "pad": "x" * (300 * 1024)}
    resp = await client.post("/api/v1/worker/heartbeat", json=huge, headers=node["headers"])
    assert resp.status_code == 413


async def test_legacy_heartbeat_still_works_for_old_keys(client, make_user):
    _, provider = await make_user("provider")
    reg = await client.post(
        "/api/v1/nodes/register", json={"name": "x", "public_key": "p", "region": "r"}, headers=provider
    )
    key = reg.json()["api_key"]
    resp = await client.post(
        f"/api/v1/nodes/{reg.json()['node_id']}/heartbeat", headers={"Authorization": f"Bearer {key}"}
    )
    assert resp.status_code == 200


async def test_graceful_disconnect_stops_scheduling_immediately(client, db, enroll_node, make_user, ollama_model):
    node = await enroll_node()
    assert (await client.post("/api/v1/worker/disconnect", json={}, headers=node["headers"])).status_code == 200
    assert (await db.get(Node, uuid.UUID(node["node_id"]))).status == "OFFLINE"
    _, customer = await make_user("customer")
    resp = await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)
    assert resp.status_code == 503
    # The next heartbeat brings it back.
    await client.post("/api/v1/worker/heartbeat", json={"worker_version": "t"}, headers=node["headers"])
    resp = await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)
    assert resp.status_code == 201
