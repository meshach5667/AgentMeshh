"""Paystack top-ups (customers), payouts (providers), and the Paystack webhook."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_roles
from app.models.user import UserRole
from app.schemas.billing import (
    PaymentOut,
    PayoutAccountOut,
    PayoutAccountSet,
    PayoutCreate,
    PayoutOut,
    TopupCreate,
)
from app.services import payments_service, paystack

router = APIRouter()
logger = logging.getLogger(__name__)
customer_only = require_roles(UserRole.customer)
provider_only = require_roles(UserRole.provider)


@router.get("/config")
async def config():
    """Whether payments are enabled, test or live mode, the currency, and limits."""
    return payments_service.payments_config()


@router.post("/topups", response_model=PaymentOut, status_code=201)
async def create_topup(req: TopupCreate, db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    """Start a Paystack checkout. Redirect the customer to ``authorization_url``; the wallet is credited only
    after Paystack confirms the payment (webhook or verify)."""
    return await payments_service.create_topup(db, user, req.amount)


@router.get("/topups", response_model=list[PaymentOut])
async def list_topups(db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    return await payments_service.list_topups(db, user)


@router.post("/topups/{reference}/verify", response_model=PaymentOut)
async def verify_topup(reference: str, db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    return await payments_service.verify_topup(db, user, reference[:100])


@router.post("/paystack/webhook", include_in_schema=False)
async def paystack_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.payments_enabled:
        raise HTTPException(status_code=503, detail="Payments are not configured")
    client = request.client.host if request.client else ""
    if settings.PAYSTACK_WEBHOOK_IPS and client not in settings.PAYSTACK_WEBHOOK_IPS:
        logger.warning("Paystack webhook from unexpected address %s rejected", client)
        raise HTTPException(status_code=403, detail="Forbidden")
    raw = await request.body()
    if not paystack.signature_valid(raw, request.headers.get("x-paystack-signature")):
        logger.warning("Paystack webhook with an invalid signature rejected")
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    outcome = await payments_service.handle_webhook(db, payload)
    logger.info("Paystack webhook %s: %s", payload.get("event"), outcome)
    return {"status": "ok"}


@router.get("/banks")
async def banks(_user=Depends(provider_only)):
    return await payments_service.list_banks()


@router.get("/payout-account", response_model=PayoutAccountOut | None)
async def get_payout_account(db: AsyncSession = Depends(get_db), user=Depends(provider_only)):
    return await payments_service.get_payout_account(db, user)


@router.put("/payout-account", response_model=PayoutAccountOut)
async def set_payout_account(req: PayoutAccountSet, db: AsyncSession = Depends(get_db), user=Depends(provider_only)):
    """Verify the account with Paystack and register it as a transfer recipient. Only the last four digits
    are stored."""
    return await payments_service.set_payout_account(db, user, req.account_number, req.bank_code)


@router.get("/payouts", response_model=list[PayoutOut])
async def list_payouts(db: AsyncSession = Depends(get_db), user=Depends(provider_only)):
    return await payments_service.list_payouts(db, user)


@router.post("/payouts", response_model=PayoutOut, status_code=201)
async def request_payout(req: PayoutCreate, db: AsyncSession = Depends(get_db), user=Depends(provider_only)):
    """Hold ``amount`` from the wallet and queue a transfer (after operator approval when required)."""
    return await payments_service.request_payout(db, user, req.amount)
