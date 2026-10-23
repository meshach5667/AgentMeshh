"""Backend authorization regressions fixed in Phase 1."""

import uuid

import pytest

from app.core.config import settings
from app.models import Deployment, Node, UsageRecord


@pytest.mark.parametrize("role", ["admin", "operator"])
async def test_privileged_roles_cannot_self_register(client, role):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": f"{role}@example.com", "password": "long-enough-pw", "role": role}
    )
    assert resp.status_code == 422


async def test_customer_registration_creates_profile_and_logs_in(client):
    body = {"email": "dev@example.com", "password": "long-enough-pw", "role": "customer"}
    resp = await client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 200, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": body["email"], "password": body["password"]})
    assert login.status_code == 200
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["role"] == "customer"


async def test_short_password_rejected(client):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "short", "role": "customer"}
    )
    assert resp.status_code == 422


async def test_inactive_user_token_rejected(client, make_user):
    _, headers = await make_user("customer", is_active=False)
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_token_for_unknown_user_rejected(client, auth_headers):
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 401


async def test_model_creation_requires_staff(client, make_user):
    payload = {
        "name": "evil",
        "version": "1",
        "runtime": "ollama",
        "source": "http://169.254.169.254/",
        "minimum_vram": 0,
        "minimum_ram": 1,
        "minimum_cpu": 1,
        "storage_requirement": 1,
        "supported_gpu_families": {},
        "deployment_config": {},
    }
    assert (await client.post("/api/v1/models", json=payload)).status_code == 401
    _, customer = await make_user("customer")
    assert (await client.post("/api/v1/models", json=payload, headers=customer)).status_code == 403

    _, operator = await make_user("operator")
    resp = await client.post("/api/v1/models", json=payload, headers=operator)
    assert resp.status_code == 200, resp.text
    # Newly created entries are not deployable until explicitly approved.
    assert resp.json()["is_approved"] is False
    assert all(m["name"] != "evil" for m in (await client.get("/api/v1/models")).json())


async def _deployment_for(db, customer_user, model):
    from sqlalchemy import select

    from app.models import Customer

    customer = (await db.execute(select(Customer).where(Customer.user_id == customer_user.id))).scalars().one()
    dep = Deployment(customer_id=customer.id, model_id=model.id, config={}, status="REQUESTED")
    db.add(dep)
    await db.commit()
    return dep


async def test_cross_customer_deployment_access_denied(client, db, make_user, approved_model):
    alice, alice_h = await make_user("customer")
    _, bob_h = await make_user("customer")
    dep = await _deployment_for(db, alice, approved_model)

    assert (await client.get(f"/api/v1/deployments/{dep.id}", headers=alice_h)).status_code == 200
    assert (await client.get(f"/api/v1/deployments/{dep.id}", headers=bob_h)).status_code == 404
    assert (await client.post(f"/api/v1/deployments/{dep.id}/stop", headers=bob_h)).status_code == 404
    assert (await client.get(f"/api/v1/usage/{dep.id}", headers=bob_h)).status_code == 404

    _, operator_h = await make_user("operator")
    assert (await client.get(f"/api/v1/deployments/{dep.id}", headers=operator_h)).status_code == 200


async def test_usage_scoped_to_owner(client, db, make_user, approved_model):
    alice, alice_h = await make_user("customer")
    dep = await _deployment_for(db, alice, approved_model)
    db.add(UsageRecord(deployment_id=dep.id, gpu_seconds=1, cpu_seconds=2))
    await db.commit()
    resp = await client.get(f"/api/v1/usage/{dep.id}", headers=alice_h)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_malformed_ids_return_404(client, make_user):
    _, headers = await make_user("customer")
    assert (await client.get("/api/v1/deployments/not-a-uuid", headers=headers)).status_code == 404
    assert (await client.get("/api/v1/nodes/not-a-uuid", headers=headers)).status_code == 404


async def test_deployment_requires_approved_model(client, make_user):
    _, headers = await make_user("customer")
    resp = await client.post("/api/v1/deployments", json={"model_id": str(uuid.uuid4())}, headers=headers)
    assert resp.status_code == 404


async def test_provider_cannot_create_deployment(client, make_user, approved_model):
    _, headers = await make_user("provider")
    resp = await client.post("/api/v1/deployments", json={"model_id": str(approved_model.id)}, headers=headers)
    assert resp.status_code == 403


async def _register_node(client, headers):
    resp = await client.post(
        "/api/v1/nodes/register",
        json={"name": "box", "public_key": "pem", "region": "eu-west"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_node_registration_requires_provider(client, make_user):
    _, customer_h = await make_user("customer")
    resp = await client.post(
        "/api/v1/nodes/register", json={"name": "x", "public_key": "pem", "region": "r"}, headers=customer_h
    )
    assert resp.status_code == 403


async def test_node_detail_is_owner_only_and_hides_credentials(client, make_user):
    _, owner_h = await make_user("provider")
    _, other_h = await make_user("provider")
    node = await _register_node(client, owner_h)

    assert (await client.get(f"/api/v1/nodes/{node['node_id']}")).status_code == 401
    assert (await client.get(f"/api/v1/nodes/{node['node_id']}", headers=other_h)).status_code == 404
    resp = await client.get(f"/api/v1/nodes/{node['node_id']}", headers=owner_h)
    assert resp.status_code == 200
    assert "api_key_hash" not in resp.json()
    assert "api_key" not in resp.json()


async def test_heartbeat_requires_matching_node_key(client, db, make_user):
    _, owner_h = await make_user("provider")
    a = await _register_node(client, owner_h)
    b = await _register_node(client, owner_h)
    url = f"/api/v1/nodes/{a['node_id']}/heartbeat"

    assert (await client.post(url)).status_code == 401
    assert (await client.post(url, headers={"Authorization": f"Bearer {b['api_key']}"})).status_code == 401
    assert (await client.post(url, headers={"Authorization": f"Bearer {a['api_key']}"})).status_code == 200

    node = await db.get(Node, uuid.UUID(a["node_id"]))
    node.status = "SUSPENDED"
    await db.commit()
    assert (await client.post(url, headers={"Authorization": f"Bearer {a['api_key']}"})).status_code == 403


async def test_test_credits_disabled_outside_dev(client, make_user, monkeypatch):
    _, headers = await make_user("customer")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    resp = await client.post("/api/v1/wallets/deposit", json={"amount": "10"}, headers=headers)
    assert resp.status_code == 403


async def test_test_credits_labelled_in_dev(client, make_user, monkeypatch):
    _, headers = await make_user("customer")
    monkeypatch.setattr(settings, "ENVIRONMENT", "dev")
    monkeypatch.setattr(settings, "ALLOW_TEST_CREDITS", True)
    resp = await client.post("/api/v1/wallets/deposit", json={"amount": "10"}, headers=headers)
    assert resp.status_code == 200, resp.text
    txs = (await client.get("/api/v1/transactions", headers=headers)).json()
    assert txs[0]["reference"] == "test-credit"
