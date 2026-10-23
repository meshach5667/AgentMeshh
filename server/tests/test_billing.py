"""Phase 7: pricing versions, rating READY time and tokens into charges, ledger settlement, prepaid checks."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.core.timeutil import utcnow
from app.models import Charge, Deployment, DeploymentEvent, PricingRule, UsageRecord, Wallet
from app.models.transaction import Transaction
from app.services import billing_service, reconciliation_service
from app.services.billing_service import Interval, ready_intervals

PRICES = {
    "cpu_core_hour": "10",
    "ram_gb_hour": "20",
    "vram_gb_hour": "0",
    "input_tokens_per_million": "1000",
    "output_tokens_per_million": "2000",
    "platform_fee_rate": "0.1",
}


async def _price(db, version=1, effective=None, **over) -> PricingRule:
    rule = PricingRule(
        id=uuid.uuid4(),
        version=version,
        currency="NGN",
        effective_from=effective or utcnow() - timedelta(days=1),
        **{k: Decimal(v) for k, v in (PRICES | over).items()},
    )
    db.add(rule)
    await db.commit()
    return rule


async def _ready_deployment(client, db, enroll_node, make_user, model, *, credit="1000", provider=None):
    node = await enroll_node(provider=provider)
    customer_user, customer = await make_user("customer")
    if credit:
        await client.post("/api/v1/wallets/deposit", json={"amount": credit}, headers=customer)
    resp = await client.post("/api/v1/deployments", json={"model_id": str(model.id)}, headers=customer)
    assert resp.status_code == 201, resp.text
    dep = resp.json()
    await client.post(
        f"/api/v1/worker/deployments/{dep['id']}/status", json={"state": "READY"}, headers=node["headers"]
    )
    return dep, node, customer_user, customer


async def _set_ready_at(db, dep_id: str, when):
    """Move the deployment's history so READY began at ``when`` (tests control time)."""
    did = uuid.UUID(dep_id)
    await db.execute(
        update(DeploymentEvent)
        .where(DeploymentEvent.deployment_id == did)
        .values(created_at=when - timedelta(minutes=1))
    )
    await db.execute(
        update(DeploymentEvent)
        .where(DeploymentEvent.deployment_id == did, DeploymentEvent.to_status == "READY")
        .values(created_at=when)
    )
    await db.execute(update(Deployment).where(Deployment.id == did).values(created_at=when - timedelta(minutes=2)))
    await db.commit()


async def _wallet(db, user_id) -> Decimal:
    db.expire_all()
    w = (await db.execute(select(Wallet).where(Wallet.user_id == user_id))).scalars().first()
    return Decimal(w.balance) if w else Decimal(0)


def test_ready_intervals_follow_lifecycle_events():
    t0 = utcnow()
    n1, n2 = uuid.uuid4(), uuid.uuid4()

    def ev(minutes, to, node):
        return DeploymentEvent(to_status=to, created_at=t0 + timedelta(minutes=minutes), node_id=node)

    events = [
        ev(0, "SCHEDULED", n1),
        ev(1, "READY", n1),
        ev(31, "UNHEALTHY", n1),
        ev(40, "SCHEDULED", n2),
        ev(45, "READY", n2),
    ]
    out = ready_intervals(events, t0 + timedelta(minutes=60), None)
    assert out == [
        Interval(t0 + timedelta(minutes=1), t0 + timedelta(minutes=31), n1),
        Interval(t0 + timedelta(minutes=45), t0 + timedelta(minutes=60), n2),
    ]


async def test_no_price_means_measured_but_free(client, db, enroll_node, make_user, ollama_model):
    dep, *_ = await _ready_deployment(client, db, enroll_node, make_user, ollama_model, credit=None)
    assert await billing_service.run_billing(utcnow() + timedelta(hours=2)) == 0
    assert (await db.execute(select(Charge))).scalars().all() == []
    pricing = (await client.get("/api/v1/billing/pricing")).json()
    assert pricing["current"] is None and pricing["currency"] == "NGN"


async def test_ready_time_and_tokens_are_charged_and_split(client, db, enroll_node, make_user, ollama_model):
    rule = await _price(db)
    provider_user, provider = await make_user("provider")
    dep, node, customer_user, customer = await _ready_deployment(
        client, db, enroll_node, make_user, ollama_model, provider=provider, credit="5000"
    )
    start = utcnow() - timedelta(hours=1)
    await _set_ready_at(db, dep["id"], start)
    db.add(
        UsageRecord(
            kind="inference",
            deployment_id=uuid.UUID(dep["id"]),
            node_id=uuid.UUID(node["node_id"]),
            request_id=uuid.uuid4().hex,
            input_tokens=500_000,
            output_tokens=250_000,
            created_at=start + timedelta(minutes=5),
        )
    )
    await db.commit()

    now = start + timedelta(hours=1)
    assert await billing_service.run_billing(now) == 1
    charge = (await db.execute(select(Charge))).scalars().one()
    # 1 h x (1 core x 10 + 1 GB x 20) = 30; tokens 0.5M x 1000/M + 0.25M x 2000/M = 1000
    assert charge.ready_seconds == pytest.approx(3600, abs=1)
    assert (charge.cpu_cores, charge.ram_mb) == (1, 1024)
    assert charge.resource_amount == pytest.approx(Decimal(30), abs=Decimal("0.01"))
    assert charge.token_amount == Decimal(1000)
    assert charge.platform_fee + charge.provider_amount == charge.amount
    assert charge.pricing_rule_id == rule.id
    assert charge.platform_fee == (charge.amount * Decimal("0.1")).quantize(Decimal("0.00000001"))

    amount, provider_amount = charge.amount, charge.provider_amount
    customer_id, provider_id = customer_user.id, provider_user.id
    assert await _wallet(db, customer_id) == Decimal(5000) - amount
    assert await _wallet(db, provider_id) == provider_amount

    # Running again for the same instant is a no-op; a later run only rates the new time.
    assert await billing_service.run_billing(now) == 0
    assert await billing_service.run_billing(now + timedelta(minutes=10)) == 1
    second = (await db.execute(select(Charge).order_by(Charge.period_start.desc()))).scalars().first()
    assert second.period_start == now and second.ready_seconds == pytest.approx(600, abs=1)

    report = await reconciliation_service.report(db)
    assert report["ok"], report["issues"]

    mine = (await client.get("/api/v1/billing/charges", headers=customer)).json()
    assert len(mine) == 2 and {c["deployment_id"] for c in mine} == {dep["id"]}
    earned = (await client.get("/api/v1/billing/charges", headers=provider)).json()
    assert len(earned) == 2
    _, stranger = await make_user("customer")
    assert (await client.get("/api/v1/billing/charges", headers=stranger)).json() == []


async def test_price_change_mid_window_is_split(client, db, enroll_node, make_user, ollama_model):
    start = utcnow() - timedelta(hours=2)
    await _price(db, version=1, effective=start - timedelta(days=1))
    cheaper = await _price(db, version=2, effective=start + timedelta(hours=1), cpu_core_hour="0", ram_gb_hour="0")
    dep, *_ = await _ready_deployment(client, db, enroll_node, make_user, ollama_model)
    await _set_ready_at(db, dep["id"], start)
    assert await billing_service.run_billing(start + timedelta(hours=2)) == 1  # the second hour is free
    charge = (await db.execute(select(Charge))).scalars().one()
    assert charge.period_end == cheaper.effective_from
    assert charge.resource_amount == pytest.approx(Decimal(30), abs=Decimal("0.01"))


async def test_unhealthy_time_is_not_charged(client, db, enroll_node, make_user, ollama_model):
    await _price(db)
    dep, *_ = await _ready_deployment(client, db, enroll_node, make_user, ollama_model)
    start = utcnow() - timedelta(hours=1)
    await _set_ready_at(db, dep["id"], start)
    db.add(
        DeploymentEvent(
            deployment_id=uuid.UUID(dep["id"]),
            from_status="READY",
            to_status="UNHEALTHY",
            actor="system",
            created_at=start + timedelta(minutes=15),
        )
    )
    await db.commit()
    await billing_service.run_billing(start + timedelta(hours=1))
    charge = (await db.execute(select(Charge))).scalars().one()
    assert charge.ready_seconds == pytest.approx(900, abs=1)


async def test_deploy_requires_prepaid_balance_and_releases_capacity(client, db, enroll_node, make_user, ollama_model):
    await _price(db)  # 30 NGN/h for this model's 1 core / 1 GB reservation
    node = await enroll_node()
    _, customer = await make_user("customer")
    resp = await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["code"] == "insufficient_balance" and Decimal(detail["required"]) == Decimal(30)
    shown = (await client.get(f"/api/v1/nodes/{node['node_id']}", headers=node["provider_headers"])).json()
    assert shown["reserved_ram_mb"] == 0 and shown["reserved_cpu_cores"] == 0

    await client.post("/api/v1/wallets/deposit", json={"amount": "30"}, headers=customer)
    assert (
        await client.post("/api/v1/deployments", json={"model_id": str(ollama_model.id)}, headers=customer)
    ).status_code == 201


async def test_exhausted_balance_stops_deployments(client, db, enroll_node, make_user, ollama_model):
    await _price(db)
    dep, _, customer_user, _ = await _ready_deployment(client, db, enroll_node, make_user, ollama_model, credit="40")
    start = utcnow() - timedelta(hours=2)
    await _set_ready_at(db, dep["id"], start)
    await billing_service.run_billing(start + timedelta(hours=2))  # 60 NGN against 40
    customer_id = customer_user.id
    assert await _wallet(db, customer_id) < 0
    db.expire_all()
    stopped = await db.get(Deployment, uuid.UUID(dep["id"]))
    assert stopped.status == "STOPPING" and stopped.error_code == "INSUFFICIENT_FUNDS"
    assert (await reconciliation_service.report(db))["ok"]


async def test_pricing_versions_are_staff_only_and_cannot_be_backdated(client, make_user):
    _, customer = await make_user("customer")
    _, operator = await make_user("operator")
    body = PRICES | {"notes": "launch prices"}
    assert (await client.post("/api/v1/admin/pricing", json=body, headers=customer)).status_code == 403
    first = await client.post("/api/v1/admin/pricing", json=body, headers=operator)
    assert first.status_code == 201 and first.json()["version"] == 1
    second = await client.post("/api/v1/admin/pricing", json=body | {"cpu_core_hour": "12"}, headers=operator)
    assert second.json()["version"] == 2
    past = (utcnow() - timedelta(days=1)).isoformat()
    assert (
        await client.post("/api/v1/admin/pricing", json=body | {"effective_from": past}, headers=operator)
    ).status_code == 422
    assert (
        await client.post("/api/v1/admin/pricing", json=body | {"platform_fee_rate": "0.9"}, headers=operator)
    ).status_code == 422
    current = (await client.get("/api/v1/billing/pricing")).json()["current"]
    assert current["version"] == 2 and Decimal(current["cpu_core_hour"]) == 12
    audit = (await client.get("/api/v1/admin/audit-logs?action=pricing.version_created", headers=operator)).json()
    assert len(audit) == 2


async def test_reconciliation_detects_a_tampered_balance(client, db, make_user):
    user, customer = await make_user("customer")
    await client.post("/api/v1/wallets/deposit", json={"amount": "50"}, headers=customer)
    assert (await reconciliation_service.report(db))["ok"]
    await db.execute(update(Wallet).where(Wallet.user_id == user.id).values(balance=Decimal("75")))
    await db.commit()
    report = await reconciliation_service.report(db)
    assert not report["ok"]
    assert report["issues"][0]["kind"] == "wallet_balance" and report["issues"][0]["ledger"] == "50.00000000"


async def test_ledger_postings_are_idempotent(db, make_user):
    from app.models.transaction import TransactionType
    from app.services import ledger_service

    user, _ = await make_user("customer")
    wallet = await ledger_service.wallet_for_user(db, user.id)
    for _ in range(2):
        await ledger_service.post(db, key="once", type=TransactionType.DEPOSIT, amount=Decimal(5), to_wallet=wallet)
    await db.commit()
    assert await ledger_service.balance(db, wallet.id) == Decimal(5)
    assert (
        len((await db.execute(select(Transaction).where(Transaction.idempotency_key == "once"))).scalars().all()) == 1
    )


async def test_billable_output_tokens_are_bounded_by_measured_bytes(client, db, enroll_node, make_user, ollama_model):
    await _price(db, cpu_core_hour="0", ram_gb_hour="0")
    dep, node, *_ = await _ready_deployment(client, db, enroll_node, make_user, ollama_model)
    start = utcnow() - timedelta(hours=1)
    await _set_ready_at(db, dep["id"], start)
    # A runtime claiming a million output tokens for a 2 KB response is billed for at most 2048.
    db.add(
        UsageRecord(
            kind="inference",
            deployment_id=uuid.UUID(dep["id"]),
            node_id=uuid.UUID(node["node_id"]),
            request_id=uuid.uuid4().hex,
            input_tokens=0,
            output_tokens=1_000_000,
            response_bytes=2048,
            created_at=start + timedelta(minutes=1),
        )
    )
    await db.commit()
    await billing_service.run_billing(start + timedelta(hours=1))
    charge = (await db.execute(select(Charge))).scalars().one()
    assert charge.output_tokens == 2048
