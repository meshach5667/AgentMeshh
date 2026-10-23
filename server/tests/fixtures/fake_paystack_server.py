"""A stand-in for Paystack's API, for end-to-end tests only (never for production).

Serves the endpoints AgentMesh uses with Paystack's documented response shapes, keeps state in memory, and
delivers HMAC-SHA512-signed webhooks to the AgentMesh API like Paystack does. Test controls:

    POST /_test/pay/{reference}           mark a checkout paid and send charge.success
    POST /_test/transfer/{reference}/{s}  finish a transfer (success|failed|reversed) and send transfer.<s>

    FAKE_PAYSTACK_SECRET=sk_test_... FAKE_PAYSTACK_WEBHOOK=http://127.0.0.1:8000/api/v1/payments/paystack/webhook \\
      uvicorn tests.fixtures.fake_paystack_server:app --port 8090
"""

import hashlib
import hmac
import itertools
import json
import os

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

SECRET = os.environ.get("FAKE_PAYSTACK_SECRET", "")
WEBHOOK = os.environ.get("FAKE_PAYSTACK_WEBHOOK", "")
app = FastAPI()
transactions: dict[str, dict] = {}
transfers: dict[str, dict] = {}
ids = itertools.count(1000)


def _auth(authorization: str) -> None:
    if authorization != f"Bearer {SECRET}":
        raise HTTPException(401, detail={"status": False, "message": "Invalid key"})


def ok(data):
    return {"status": True, "message": "ok", "data": data}


async def _deliver(event: str, data: dict) -> int:
    body = json.dumps({"event": event, "data": data}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            WEBHOOK, content=body, headers={"x-paystack-signature": sig, "content-type": "application/json"}
        )
    return resp.status_code


@app.post("/transaction/initialize")
async def initialize(request: Request, authorization: str = Header("")):
    _auth(authorization)
    body = await request.json()
    ref = body["reference"]
    transactions[ref] = {
        "id": next(ids),
        "reference": ref,
        "status": "ongoing",
        "amount": body["amount"],
        "currency": body["currency"],
    }
    return ok(
        {"authorization_url": f"https://checkout.paystack.com/fake-{ref}", "access_code": "fake", "reference": ref}
    )


@app.get("/transaction/verify/{ref}")
async def verify(ref: str, authorization: str = Header("")):
    _auth(authorization)
    if ref not in transactions:
        raise HTTPException(404, detail={"status": False, "message": "Transaction reference not found"})
    return ok({**transactions[ref], "channel": "card"})


@app.get("/bank")
async def banks(authorization: str = Header("")):
    _auth(authorization)
    return ok(
        [
            {"name": "Fake Test Bank", "code": "001", "active": True},
            {"name": "Second Test Bank", "code": "002", "active": True},
        ]
    )


@app.get("/bank/resolve")
async def resolve(account_number: str, bank_code: str, authorization: str = Header("")):
    _auth(authorization)
    return ok({"account_number": account_number, "account_name": "E2E PROVIDER"})


@app.post("/transferrecipient")
async def recipient(request: Request, authorization: str = Header("")):
    _auth(authorization)
    body = await request.json()
    return ok({"recipient_code": f"RCP_{body['account_number'][-4:]}", "details": {"bank_name": "Fake Test Bank"}})


@app.post("/transfer")
async def transfer(request: Request, authorization: str = Header("")):
    _auth(authorization)
    body = await request.json()
    ref = body["reference"]
    transfers[ref] = {
        "id": next(ids),
        "reference": ref,
        "status": "pending",
        "amount": body["amount"],
        "transfer_code": f"TRF_{ref[-6:]}",
    }
    return ok(transfers[ref])


@app.get("/transfer/verify/{ref}")
async def verify_transfer(ref: str, authorization: str = Header("")):
    _auth(authorization)
    if ref not in transfers:
        raise HTTPException(404, detail={"status": False, "message": "Transfer not found"})
    return ok(transfers[ref])


@app.post("/_test/pay/{ref}")
async def pay(ref: str):
    transactions[ref]["status"] = "success"
    return {"webhook_status": await _deliver("charge.success", transactions[ref])}


@app.post("/_test/transfer/{ref}/{status}")
async def finish_transfer(ref: str, status: str):
    transfers[ref]["status"] = status
    return {"webhook_status": await _deliver(f"transfer.{status}", transfers[ref])}
