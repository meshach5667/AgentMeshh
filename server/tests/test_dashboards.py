"""Phase 6 read APIs behind the dashboards: public stats, usage summaries, operator views, provider earnings."""

import uuid

from app.models import Deployment
from app.models.usage import UsageRecord


async def _deploy(client, headers, model):
    resp = await client.post("/api/v1/deployments", json={"model_id": str(model.id)}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _usage(dep: dict, *, outcome="success", inp=None, out=None) -> UsageRecord:
    return UsageRecord(
        kind="inference",
        deployment_id=uuid.UUID(dep["id"]),
        node_id=uuid.UUID(dep["node_id"]),
        request_id=uuid.uuid4().hex,
        endpoint="/v1/chat/completions",
        status_code=200 if outcome == "success" else 502,
        outcome=outcome,
        input_tokens=inp,
        output_tokens=out,
        token_source="runtime_reported" if out is not None else None,
    )


async def test_public_stats_are_counts_only(client, enroll_node, make_user, ollama_model):
    empty = (await client.get("/api/v1/stats/public")).json()
    assert empty["nodes_online"] == 0 and empty["deployments_ready"] == 0
    assert empty["models_deployable"] == 1
    assert empty["features"] == {
        "test_credits": True,
        "payments": False,
        "provider_payouts": False,
        "confidential_computing": False,
    }

    node = await enroll_node(region="secret-region")
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status", json={"state": "READY"}, headers=node["headers"]
    )

    resp = await client.get("/api/v1/stats/public")
    stats = resp.json()
    assert stats["nodes_online"] == 1 and stats["gpu_nodes_online"] == 0
    assert stats["runtimes_online"] == ["ollama"] and stats["deployments_ready"] == 1
    assert "secret-region" not in resp.text and "test-node" not in resp.text and node["node_id"] not in resp.text


async def test_paused_nodes_are_not_counted_online(client, enroll_node):
    node = await enroll_node()
    await client.patch(
        f"/api/v1/nodes/{node['node_id']}", json={"accepting_workloads": False}, headers=node["provider_headers"]
    )
    assert (await client.get("/api/v1/stats/public")).json()["nodes_online"] == 0


async def test_usage_summary_is_scoped_to_the_caller(client, db, enroll_node, make_user, ollama_model):
    _, provider_a = await make_user("provider")
    _, provider_b = await make_user("provider")
    node_a = await enroll_node(provider=provider_a, ram_mb=1024)
    node_b = await enroll_node(provider=provider_b, ram_mb=1024)
    _, alice = await make_user("customer")
    _, bob = await make_user("customer")
    dep_a = await _deploy(client, alice, ollama_model)
    dep_b = await _deploy(client, bob, ollama_model)
    assert {dep_a["node_id"], dep_b["node_id"]} == {node_a["node_id"], node_b["node_id"]}

    db.add_all(
        [
            _usage(dep_a, inp=10, out=5),
            _usage(dep_a, inp=3, out=None),  # runtime reported no counts
            _usage(dep_a, outcome="runtime_error"),
            _usage(dep_b, inp=100, out=50),
        ]
    )
    await db.commit()

    mine = (await client.get("/api/v1/usage/summary", headers=alice)).json()
    assert mine["scope"] == "customer"
    assert mine["totals"] == {
        "requests": 3,
        "succeeded": 2,
        "failed": 1,
        "input_tokens": 13,
        "output_tokens": 5,
        "requests_without_token_counts": 2,
    }
    assert [d["deployment_id"] for d in mine["by_deployment"]] == [dep_a["id"]]
    assert len(mine["by_day"]) == 1 and mine["by_day"][0]["requests"] == 3

    # A provider sees what its own nodes served, whoever the customer was.
    host_of_b = provider_a if dep_b["node_id"] == node_a["node_id"] else provider_b
    served = (await client.get("/api/v1/usage/summary", headers=host_of_b)).json()
    assert served["scope"] == "provider" and served["totals"]["output_tokens"] == 50

    assert (await client.get("/api/v1/usage/summary?scope=network", headers=alice)).status_code == 403
    assert (await client.get("/api/v1/usage/summary?scope=provider", headers=alice)).status_code == 403
    _, operator = await make_user("operator")
    network = (await client.get("/api/v1/usage/summary", headers=operator)).json()
    assert network["scope"] == "network" and network["totals"]["requests"] == 4


async def test_operator_endpoints_require_staff(client, make_user):
    for role in ("customer", "provider"):
        _, headers = await make_user(role)
        for path in ("overview", "nodes", "deployments", "models", "transactions"):
            assert (await client.get(f"/api/v1/admin/{path}", headers=headers)).status_code == 403, (role, path)
    assert (await client.get("/api/v1/admin/overview")).status_code == 401


async def test_operator_views_show_the_whole_network(client, db, enroll_node, make_user, ollama_model):
    provider_user, provider = await make_user("provider")
    node = await enroll_node(provider=provider)
    customer_user, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    await client.post("/api/v1/wallets/deposit", json={"amount": 5}, headers=customer)
    _, operator = await make_user("operator")

    nodes = (await client.get("/api/v1/admin/nodes", headers=operator)).json()
    assert [(n["id"], n["owner_email"]) for n in nodes] == [(node["node_id"], provider_user.email)]
    deps = (await client.get("/api/v1/admin/deployments", headers=operator)).json()
    assert deps[0]["id"] == dep["id"] and deps[0]["customer_email"] == customer_user.email
    filtered = await client.get(f"/api/v1/admin/deployments?status=READY&node_id={node['node_id']}", headers=operator)
    assert filtered.json() == []

    overview = (await client.get("/api/v1/admin/overview", headers=operator)).json()
    assert overview["nodes_by_status"] == {"ONLINE": 1}
    assert overview["deployments_by_status"] == {"SCHEDULED": 1}
    assert overview["models"] == {"total": 1, "approved": 1, "deployable": 1}
    assert {"type": "DEPOSIT", "status": "SETTLED", "count": 1} == {
        k: v for k, v in overview["ledger"][0].items() if k != "amount"
    }
    assert len((await client.get("/api/v1/admin/transactions", headers=operator)).json()) == 1

    # Unapproved models appear only in the operator catalog.
    ollama_model.is_approved = False
    await db.commit()
    assert (await client.get("/api/v1/models")).json() == []
    assert [m["id"] for m in (await client.get("/api/v1/admin/models", headers=operator)).json()] == [
        str(ollama_model.id)
    ]


async def test_provider_earnings_count_hosted_deployments(client, db, enroll_node, make_user, ollama_model):
    _, provider = await make_user("provider")
    await enroll_node(provider=provider)
    _, customer = await make_user("customer")
    dep = await _deploy(client, customer, ollama_model)
    earnings = (await client.get("/api/v1/earnings", headers=provider)).json()
    assert earnings["total_deployments"] == 1 and earnings["active_deployments"] == 1

    row = await db.get(Deployment, uuid.UUID(dep["id"]))
    row.status = "STOPPED"
    await db.commit()
    earnings = (await client.get("/api/v1/earnings", headers=provider)).json()
    assert earnings["total_deployments"] == 1 and earnings["active_deployments"] == 0
    assert (await client.get("/api/v1/earnings/history", headers=provider)).json() == []


async def test_create_operator_script_provisions_and_promotes(client, make_user):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "create_operator.py"
    spec = importlib.util.spec_from_file_location("create_operator", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)  # type: ignore[union-attr]

    password = "a-long-operator-password"
    assert await script.create_operator("ops@example.com", "operator", False, lambda: password) == "created"
    login = await client.post("/api/v1/auth/login", json={"email": "ops@example.com", "password": password})
    assert login.status_code == 200 and login.json()["user"]["role"] == "operator"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/v1/admin/overview", headers=headers)).status_code == 200

    customer, _ = await make_user("customer")
    outcome = await script.create_operator(customer.email, "admin", False, lambda: "unused")
    assert outcome == "promoted from customer"
    audit = (await client.get("/api/v1/admin/audit-logs?action=user.operator_provisioned", headers=headers)).json()
    assert len(audit) == 2 and all("password" not in str(a["details"]) for a in audit)
