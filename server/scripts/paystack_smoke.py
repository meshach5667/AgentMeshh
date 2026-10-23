"""Check AgentMesh's Paystack integration against Paystack's real API in TEST mode.

Uses the same client code as the control plane. Needs a Paystack test secret key; no money moves.

    PAYSTACK_SECRET_KEY=sk_test_... python scripts/paystack_smoke.py
    PAYSTACK_SECRET_KEY=sk_test_... python scripts/paystack_smoke.py --pay   # wait while you pay with a test card

Steps: list banks, initialize a checkout, verify it (unpaid), optionally wait for a test-card payment and
verify success, and confirm the webhook signature scheme with a locally signed body. Webhook *delivery* must be
checked separately: set the webhook URL in the Paystack dashboard to <PUBLIC_BASE_URL>/api/v1/payments/paystack/webhook.
"""

import argparse
import asyncio
import hashlib
import hmac
import secrets
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services import paystack  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}", flush=True)
    if not ok:
        raise SystemExit(1)


async def main(pay: bool, currency: str) -> None:
    key = settings.PAYSTACK_SECRET_KEY
    why = "PAYSTACK_SECRET_KEY is not set" if not key else "only test keys (sk_test_...) are accepted"
    check("test-mode secret key configured", key.startswith("sk_test_"), "" if key.startswith("sk_test_") else why)
    banks = await paystack.list_banks(currency)
    check("list banks", len(banks) > 0, f"{len(banks)} banks for {currency}")

    reference = f"am-top-{secrets.token_hex(12)}"
    init = await paystack.initialize_transaction(
        email="smoke-test@example.com",
        amount=Decimal("100"),
        currency=currency,
        reference=reference,
        callback_url=f"{settings.FRONTEND_URL.rstrip('/')}/customer/wallet",
    )
    url = init.get("authorization_url", "")
    check("initialize checkout", url.startswith("https://"), url)
    unpaid = await paystack.verify_transaction(reference)
    check("verify unpaid checkout", unpaid.get("status") != "success", f"status={unpaid.get('status')}")
    check("amount round-trips in subunits", int(unpaid.get("amount", 0)) == 10000, str(unpaid.get("amount")))

    if pay:
        print(f"\nOpen {url} and pay with a Paystack test card (e.g. 4084 0840 8408 4081, any future expiry, CVV 408).")
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            data = await paystack.verify_transaction(reference)
            if data.get("status") == "success":
                check("test payment verified as success", True, f"channel={data.get('channel')}")
                break
            await asyncio.sleep(5)
        else:
            check("test payment verified as success", False, "not paid within 10 minutes")

    body = b'{"event":"charge.success","data":{"reference":"x"}}'
    signature = hmac.new(key.encode(), body, hashlib.sha512).hexdigest()
    check("webhook signature scheme (HMAC-SHA512 of the raw body)", paystack.signature_valid(body, signature))
    print("\nAll checks passed. Next: point the Paystack webhook at the API and make a top-up from the dashboard.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pay", action="store_true", help="wait for a manual test-card payment and verify it")
    ap.add_argument("--currency", default=settings.BILLING_CURRENCY)
    args = ap.parse_args()
    asyncio.run(main(args.pay, args.currency))
