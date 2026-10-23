"""Phase 7: Paystack top-ups, signed webhooks, idempotency, payouts, and reconciliation.

Paystack is replaced by an httpx MockTransport answering with Paystack's documented response shapes; the code
under test builds real requests and verifies real HMAC-SHA512 signatures.
"""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import Settings, settings
from app.core.timeutil import utcnow
from app.models import Payment, Payout, Wallet
from app.services import paystack, reconciliation_service

SECRET = "sk_test_" + "a" * 40


class FakePaystack:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.transactions: dict[str, dict] = {}  # reference -> verify data
        self.transfers: dict[str, dict] = {}
        self.transfer_reply: dict | Exception = {"status": "pending"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {SECRET}"
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.calls.append((request.method, path, body))
        if path == "/transaction/initialize":
            ref = body["reference"]
            self.transactions[ref] = {"status": "ongoing", "amount": body["amount"], "currency": body["currency"]}
            return ok(
                {"authorization_url": f"https://checkout.paystack.com/{ref}", "access_code": "x", "reference": ref}
            )
        if path.startswith("/transaction/verify/"):
            ref = path.rsplit("/", 1)[1]
            if ref not in self.transactions:
                return httpx.Response(404, json={"status": False, "message": "Transaction reference not found"})
            return ok({"reference": ref, "channel": "card", **self.transactions[ref]})
        if path == "/bank":
            return ok([{"name": "Test Bank", "code": "057", "active": True}])
        if path == "/bank/resolve":
            return ok({"account_number": request.url.params["account_number"], "account_name": "ADA OBI"})
        if path == "/transferrecipient":
            return ok({"recipient_code": "RCP_test123", "details": {"bank_name": "Test Bank"}})
        if path == "/transfer":
            if isinstance(self.transfer_reply, Exception):
                raise self.transfer_reply
            self.transfers[body["reference"]] = {"amount": body["amount"], **self.transfer_reply}
            return ok(
                {
                    "reference": body["reference"],
                    "transfer_code": "TRF_1",
                    "amount": body["amount"],
                    **self.transfer_reply,
                }
            )
        if path.startswith("/transfer/verify/"):
            ref = path.rsplit("/", 1)[1]
            if ref not in self.transfers:
                return httpx.Response(404, json={"status": False, "message": "Transfer not found"})
            return ok({"reference": ref, **self.transfers[ref]})
        return httpx.Response(404, json={"status": False, "message": "unknown"})


def ok(data):
    return httpx.Response(200, json={"status": True, "message": "ok", "data": data})


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "PAYOUTS_REQUIRE_APPROVAL", True)
    fake = FakePaystack()
    paystack.set_transport(httpx.MockTransport(fake))
    yield fake
    paystack.set_transport(None)


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


async def webhook(client, payload: dict, secret: str = SECRET):
    body = json.dumps(payload).encode()
    return await client.post(
        "/api/v1/payments/paystack/webhook",
        content=body,
        headers={"x-paystack-signature": sign(body, secret), "content-type": "application/json"},
    )


async def balance(db, user_id) -> Decimal:
    value = (await db.execute(select(Wallet.balance).where(Wallet.user_id == user_id))).scalar()
    return Decimal(value or 0)


async def topup(client, headers, amount="2500"):
    resp = await client.post("/api/v1/payments/topups", json={"amount": amount}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_payments_disabled_without_keys(client, make_user):
    _, customer = await make_user("customer")
    assert (await client.get("/api/v1/payments/config")).json()["enabled"] is False
    assert (await client.post("/api/v1/payments/topups", json={"amount": "500"}, headers=customer)).status_code == 503
    assert (await client.post("/api/v1/payments/paystack/webhook", content=b"{}")).status_code == 503


async def test_topup_initializes_checkout_in_subunits(client, make_user, fake):
    user, customer = await make_user("customer")
    cfg = (await client.get("/api/v1/payments/config")).json()
    assert cfg["enabled"] and cfg["mode"] == "test" and cfg["currency"] == "NGN"
    payment = await topup(client, customer, "2500.50")
    method, path, body = fake.calls[-1]
    assert (method, path) == ("POST", "/transaction/initialize")
    assert body["amount"] == 250050 and body["currency"] == "NGN" and body["email"] == user.email
    assert body["reference"] == payment["reference"] and payment["reference"].startswith("am-top-")
    assert body["callback_url"].endswith("/customer/wallet")
    assert payment["status"] == "INITIALIZED" and payment["authorization_url"].startswith(
        "https://checkout.paystack.com/"
    )
    assert (await client.post("/api/v1/payments/topups", json={"amount": "5"}, headers=customer)).status_code == 422
    _, provider = await make_user("provider")
    assert (await client.post("/api/v1/payments/topups", json={"amount": "500"}, headers=provider)).status_code == 403


async def test_signed_webhook_credits_exactly_once(client, db, make_user, fake):
    user, customer = await make_user("customer")
    payment = await topup(client, customer)
    event = {
        "event": "charge.success",
        "data": {
            "id": 9001,
            "reference": payment["reference"],
            "status": "success",
            "amount": 250000,
            "currency": "NGN",
        },
    }
    # Unsigned or wrongly signed deliveries are rejected and change nothing.
    body = json.dumps(event).encode()
    bad = await client.post("/api/v1/payments/paystack/webhook", content=body, headers={"x-paystack-signature": "00"})
    assert bad.status_code == 401
    assert (await webhook(client, event, secret="sk_test_wrong")).status_code == 401
    assert await balance(db, user.id) == 0

    for _ in range(3):  # Paystack retries deliveries
        assert (await webhook(client, event)).status_code == 200
    fake.transactions[payment["reference"]]["status"] = "success"
    verified = await client.post(f"/api/v1/payments/topups/{payment['reference']}/verify", headers=customer)
    assert verified.json()["status"] == "SUCCEEDED"
    assert await balance(db, user.id) == Decimal(2500)
    report = await reconciliation_service.report(db)
    assert report["ok"], report["issues"]

    tx = (await client.get("/api/v1/transactions", headers=customer)).json()
    assert [(t["type"], t["amount"]) for t in tx] == [("DEPOSIT", "2500.00000000")]


async def test_return_from_checkout_verifies_with_paystack(client, db, make_user, fake):
    user, customer = await make_user("customer")
    payment = await topup(client, customer, "1000")
    pending = await client.post(f"/api/v1/payments/topups/{payment['reference']}/verify", headers=customer)
    assert pending.json()["status"] == "INITIALIZED"  # customer has not paid yet
    fake.transactions[payment["reference"]]["status"] = "success"
    done = await client.post(f"/api/v1/payments/topups/{payment['reference']}/verify", headers=customer)
    assert done.json()["status"] == "SUCCEEDED" and done.json()["channel"] == "card"
    assert await balance(db, user.id) == Decimal(1000)
    # A late webhook for the same payment does not credit again.
    await webhook(
        client,
        {
            "event": "charge.success",
            "data": {
                "id": 1,
                "reference": payment["reference"],
                "status": "success",
                "amount": 100000,
                "currency": "NGN",
            },
        },
    )
    assert await balance(db, user.id) == Decimal(1000)
    _, other = await make_user("customer")
    assert (
        await client.post(f"/api/v1/payments/topups/{payment['reference']}/verify", headers=other)
    ).status_code == 404


async def test_amount_mismatch_is_held_for_review(client, db, make_user, fake):
    user, customer = await make_user("customer")
    payment = await topup(client, customer, "5000")
    await webhook(
        client,
        {
            "event": "charge.success",
            "data": {"id": 2, "reference": payment["reference"], "status": "success", "amount": 100, "currency": "NGN"},
        },
    )
    assert await balance(db, user.id) == 0
    stored = (await db.execute(select(Payment).where(Payment.reference == payment["reference"]))).scalars().one()
    assert stored.status == "REVIEW"
    report = await reconciliation_service.report(db)
    assert [i["kind"] for i in report["issues"]] == ["payment_needs_review"]


async def test_failed_and_unknown_payments(client, db, make_user, fake):
    user, customer = await make_user("customer")
    payment = await topup(client, customer)
    fake.transactions[payment["reference"]].update(status="failed", gateway_response="Declined")
    resp = await client.post(f"/api/v1/payments/topups/{payment['reference']}/verify", headers=customer)
    assert resp.json()["status"] == "FAILED" and resp.json()["failure_reason"] == "Declined"
    assert (
        await webhook(client, {"event": "charge.success", "data": {"id": 3, "reference": "am-top-nope"}})
    ).status_code == 200
    assert await balance(db, user.id) == 0


async def test_reconciliation_resolves_abandoned_and_late_payments(client, db, make_user, fake):
    user, customer = await make_user("customer")
    paid = await topup(client, customer, "700")
    abandoned = await topup(client, customer, "300")
    fake.transactions[paid["reference"]]["status"] = "success"
    fake.transactions[abandoned["reference"]]["status"] = "abandoned"
    await db.execute(update(Payment).values(created_at=utcnow() - timedelta(hours=2)))
    await db.commit()
    result = await reconciliation_service.run()
    assert result["payments"] == {paid["reference"]: "credited", abandoned["reference"]: "abandoned"}
    assert await balance(db, user.id) == Decimal(700)


async def _provider_with_earnings(client, make_user, amount="5000"):
    user, provider = await make_user("provider")
    await client.post("/api/v1/wallets/deposit", json={"amount": amount}, headers=provider)
    acct = await client.put(
        "/api/v1/payments/payout-account", json={"account_number": "0123456789", "bank_code": "057"}, headers=provider
    )
    assert acct.status_code == 200, acct.text
    assert acct.json()["account_last4"] == "6789" and acct.json()["account_name"] == "ADA OBI"
    assert "0123456789" not in acct.text
    return user, provider


async def test_payout_held_approved_and_settled_by_webhook(client, db, make_user, fake):
    user, provider = await _provider_with_earnings(client, make_user)
    _, operator = await make_user("operator")
    too_much = await client.post("/api/v1/payments/payouts", json={"amount": "6000"}, headers=provider)
    assert too_much.status_code == 409
    payout = (await client.post("/api/v1/payments/payouts", json={"amount": "3000"}, headers=provider)).json()
    assert payout["status"] == "REQUESTED" and payout["reference"].startswith("am-po-")
    assert await balance(db, user.id) == Decimal(2000)  # held
    assert not any(path == "/transfer" for _, path, _ in fake.calls)  # nothing sent before approval

    _, other_provider = await make_user("provider")
    assert (
        await client.post(f"/api/v1/admin/payouts/{payout['id']}/approve", headers=other_provider)
    ).status_code == 403
    approved = (await client.post(f"/api/v1/admin/payouts/{payout['id']}/approve", headers=operator)).json()
    assert approved["status"] == "PENDING"
    transfer = next(body for _, path, body in fake.calls if path == "/transfer")
    assert (
        transfer["amount"] == 300000
        and transfer["recipient"] == "RCP_test123"
        and transfer["reference"] == payout["reference"]
    )
    assert (await client.post(f"/api/v1/admin/payouts/{payout['id']}/approve", headers=operator)).status_code == 409

    event = {
        "event": "transfer.success",
        "data": {"id": 77, "reference": payout["reference"], "status": "success", "amount": 300000},
    }
    await webhook(client, event)
    await webhook(client, event)
    final = (await client.get("/api/v1/payments/payouts", headers=provider)).json()[0]
    assert final["status"] == "SUCCEEDED"
    assert await balance(db, user.id) == Decimal(2000)
    assert (await reconciliation_service.report(db))["ok"]


async def test_failed_reversed_and_rejected_payouts_return_funds(client, db, make_user, fake):
    user, provider = await _provider_with_earnings(client, make_user)
    _, operator = await make_user("operator")
    p1 = (await client.post("/api/v1/payments/payouts", json={"amount": "1000"}, headers=provider)).json()
    p2 = (await client.post("/api/v1/payments/payouts", json={"amount": "1500"}, headers=provider)).json()
    p3 = (await client.post("/api/v1/payments/payouts", json={"amount": "2000"}, headers=provider)).json()
    assert await balance(db, user.id) == Decimal(500)
    for p in (p1, p2):
        await client.post(f"/api/v1/admin/payouts/{p['id']}/approve", headers=operator)
    await webhook(
        client,
        {
            "event": "transfer.failed",
            "data": {
                "id": 1,
                "reference": p1["reference"],
                "status": "failed",
                "amount": 100000,
                "reason": "Account closed",
            },
        },
    )
    await webhook(
        client,
        {
            "event": "transfer.reversed",
            "data": {"id": 2, "reference": p2["reference"], "status": "reversed", "amount": 150000},
        },
    )
    rejected = await client.post(
        f"/api/v1/admin/payouts/{p3['id']}/reject", json={"reason": "Verify identity"}, headers=operator
    )
    assert rejected.json()["status"] == "REJECTED"
    statuses = {
        p["reference"]: (p["status"], p["failure_reason"])
        for p in (await client.get("/api/v1/payments/payouts", headers=provider)).json()
    }
    assert statuses[p1["reference"]] == ("FAILED", "Account closed")
    assert statuses[p2["reference"]][0] == "REVERSED"
    assert statuses[p3["reference"]] == ("REJECTED", "Verify identity")
    assert await balance(db, user.id) == Decimal(5000)
    assert (await reconciliation_service.report(db))["ok"]


async def test_uncertain_transfer_is_reconciled_not_refunded(client, db, make_user, fake):
    user, provider = await _provider_with_earnings(client, make_user)
    _, operator = await make_user("operator")
    p = (await client.post("/api/v1/payments/payouts", json={"amount": "2000"}, headers=provider)).json()
    fake.transfer_reply = httpx.ReadTimeout("slow")
    out = (await client.post(f"/api/v1/admin/payouts/{p['id']}/approve", headers=operator)).json()
    assert out["status"] == "PENDING" and "Outcome unknown" in out["failure_reason"]
    assert await balance(db, user.id) == Decimal(3000)  # still held: the transfer may have happened

    # Paystack did make the transfer; reconciliation finds it and confirms.
    fake.transfers[p["reference"]] = {"status": "success", "amount": 200000}
    await db.execute(update(Payout).values(updated_at=utcnow() - timedelta(hours=2)))
    await db.commit()
    result = await reconciliation_service.run()
    assert result["payouts"][p["reference"]] == "succeeded; reconciled"
    done = (await client.get("/api/v1/payments/payouts", headers=provider)).json()[0]
    assert done["status"] == "SUCCEEDED" and done["reconciled_at"]
    assert await balance(db, user.id) == Decimal(3000)


async def test_transfer_unknown_to_paystack_is_refunded_by_reconciliation(client, db, make_user, fake):
    user, provider = await _provider_with_earnings(client, make_user)
    _, operator = await make_user("operator")
    p = (await client.post("/api/v1/payments/payouts", json={"amount": "2000"}, headers=provider)).json()
    fake.transfer_reply = httpx.ReadTimeout("slow")
    await client.post(f"/api/v1/admin/payouts/{p['id']}/approve", headers=operator)
    await db.execute(update(Payout).values(updated_at=utcnow() - timedelta(hours=2)))
    await db.commit()
    await reconciliation_service.run()
    final = (await client.get("/api/v1/payments/payouts", headers=provider)).json()[0]
    assert final["status"] == "FAILED"
    assert await balance(db, user.id) == Decimal(5000)


async def test_payout_needs_account_and_minimum(client, make_user, fake):
    _, provider = await make_user("provider")
    await client.post("/api/v1/wallets/deposit", json={"amount": "5000"}, headers=provider)
    assert (await client.post("/api/v1/payments/payouts", json={"amount": "2000"}, headers=provider)).status_code == 409
    _, provider2 = await _provider_with_earnings(client, make_user)
    assert (await client.post("/api/v1/payments/payouts", json={"amount": "10"}, headers=provider2)).status_code == 422
    _, customer = await make_user("customer")
    assert (await client.post("/api/v1/payments/payouts", json={"amount": "2000"}, headers=customer)).status_code == 403


async def test_reconciliation_and_admin_endpoints_are_staff_only(client, make_user, fake):
    _, customer = await make_user("customer")
    _, operator = await make_user("operator")
    for path in ("/api/v1/admin/reconciliation", "/api/v1/admin/payouts", "/api/v1/admin/pricing"):
        assert (await client.get(path, headers=customer)).status_code == 403
        assert (await client.get(path, headers=operator)).status_code == 200
    assert (await client.post("/api/v1/admin/reconciliation/run", headers=customer)).status_code == 403


def test_payment_settings_validation():
    base = {"_env_file": None}
    Settings(PAYSTACK_SECRET_KEY="sk_test_x", **base)
    with pytest.raises(ValueError, match="secret key"):
        Settings(PAYSTACK_SECRET_KEY="pk_test_x", **base)
    with pytest.raises(ValueError, match="PAYSTACK_ALLOW_LIVE"):
        Settings(PAYSTACK_SECRET_KEY="sk_live_x", **base)
    assert Settings(PAYSTACK_SECRET_KEY="sk_live_x", PAYSTACK_ALLOW_LIVE=True, **base).payments_mode == "live"


def test_subunit_conversion_refuses_fractions():
    assert paystack.to_subunits(Decimal("12.34")) == 1234
    with pytest.raises(ValueError):
        paystack.to_subunits(Decimal("0.001"))
    assert paystack.signature_valid(b"{}", sign(b"{}"), SECRET)
    assert not paystack.signature_valid(b"{}", None, SECRET)
    assert not paystack.signature_valid(b"{}", sign(b"{}"), "")
