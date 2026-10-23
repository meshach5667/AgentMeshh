"""Minimal Paystack API client (https://paystack.com/docs/api).

Amounts cross this boundary in the currency's subunit (kobo for NGN): Paystack integers, never floats.
Webhooks are authenticated with HMAC-SHA512 of the raw request body keyed by the secret key.
"""

import hashlib
import hmac
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings

SUBUNITS = 100  # NGN, GHS, ZAR, KES and USD all use 1/100 subunits on Paystack


class PaystackError(Exception):
    """Paystack refused the request or answered unexpectedly. ``uncertain`` means the outcome is unknown
    (timeout or connection error after sending) and must be resolved by verification, not assumed failed."""

    def __init__(self, message: str, *, status: int | None = None, uncertain: bool = False):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain


def to_subunits(amount: Decimal) -> int:
    value = Decimal(amount) * SUBUNITS
    if value != value.to_integral_value():
        raise ValueError(f"{amount} has more precision than the currency allows")
    return int(value)


def from_subunits(value: int | str) -> Decimal:
    return Decimal(int(value)) / SUBUNITS


def signature_valid(raw_body: bytes, signature: str | None, secret: str | None = None) -> bool:
    secret = secret if secret is not None else settings.PAYSTACK_SECRET_KEY
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


# Tests replace this to route requests to a fake Paystack (httpx.MockTransport).
_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


async def _call(method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> dict[str, Any]:
    if not settings.PAYSTACK_SECRET_KEY:
        raise PaystackError("Payments are not configured (PAYSTACK_SECRET_KEY is not set)", status=503)
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            base_url=settings.PAYSTACK_BASE_URL,
            timeout=settings.PAYSTACK_TIMEOUT_SECONDS,
            transport=_transport,
        ) as client:
            resp = await client.request(method, path, json=json, params=params, headers=headers)
    except httpx.ConnectError as exc:
        raise PaystackError(f"Could not reach Paystack: {type(exc).__name__}") from None
    except httpx.HTTPError as exc:
        # The request may have reached Paystack; its outcome is unknown.
        raise PaystackError(f"Paystack request did not complete: {type(exc).__name__}", uncertain=True) from None
    try:
        body = resp.json()
    except ValueError:
        raise PaystackError(
            f"Paystack returned HTTP {resp.status_code} without JSON", status=resp.status_code
        ) from None
    if resp.status_code >= 500:
        raise PaystackError(f"Paystack error (HTTP {resp.status_code})", status=resp.status_code, uncertain=True)
    if resp.status_code >= 400 or not body.get("status"):
        raise PaystackError(str(body.get("message") or f"HTTP {resp.status_code}")[:300], status=resp.status_code)
    return body.get("data") or {}


async def initialize_transaction(*, email: str, amount: Decimal, currency: str, reference: str, callback_url: str):
    return await _call(
        "POST",
        "/transaction/initialize",
        json={
            "email": email,
            "amount": to_subunits(amount),
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": {"purpose": "agentmesh_wallet_topup"},
        },
    )


async def verify_transaction(reference: str) -> dict[str, Any]:
    return await _call("GET", f"/transaction/verify/{reference}")


async def list_banks(currency: str) -> list[dict[str, Any]]:
    data = await _call("GET", "/bank", params={"currency": currency, "perPage": 200})
    return data if isinstance(data, list) else []


async def resolve_account(account_number: str, bank_code: str) -> dict[str, Any]:
    return await _call("GET", "/bank/resolve", params={"account_number": account_number, "bank_code": bank_code})


async def create_recipient(*, name: str, account_number: str, bank_code: str, currency: str) -> dict[str, Any]:
    return await _call(
        "POST",
        "/transferrecipient",
        json={
            "type": "nuban" if currency == "NGN" else "basa" if currency == "ZAR" else "mobile_money",
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        },
    )


async def initiate_transfer(*, amount: Decimal, recipient: str, reference: str, reason: str) -> dict[str, Any]:
    return await _call(
        "POST",
        "/transfer",
        json={
            "source": "balance",
            "amount": to_subunits(amount),
            "recipient": recipient,
            "reference": reference,
            "reason": reason,
        },
    )


async def verify_transfer(reference: str) -> dict[str, Any]:
    return await _call("GET", f"/transfer/verify/{reference}")
