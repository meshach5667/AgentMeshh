"""Reconciliation: resolve stale payments and payouts against Paystack, and check the ledger's invariants.

``run`` asks Paystack about top-ups and payouts that are still open after RECONCILE_AFTER_MINUTES and applies
the answer through the same code as webhooks. ``report`` never changes anything; it lists discrepancies:

* a wallet balance that differs from its ledger (settled credits minus pending and settled debits);
* a charge whose debit differs from its provider credit plus platform fee, or that lacks its debit;
* a SUCCEEDED top-up without exactly one matching deposit, or a deposit for a payment that did not succeed;
* a payout whose hold does not match its state.
"""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import session_scope
from app.core.timeutil import utcnow
from app.models.billing import Charge, Payment, PaymentStatus, Payout, PayoutStatus
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.wallet import Wallet
from app.services import payments_service, paystack
from app.services.ledger_service import DEBIT_STATES, money
from app.services.paystack import PaystackError

logger = logging.getLogger(__name__)

HOLD_FOR = {
    PayoutStatus.REQUESTED.value: TransactionStatus.PENDING.value,
    PayoutStatus.PENDING.value: TransactionStatus.PENDING.value,
    PayoutStatus.OTP_REQUIRED.value: TransactionStatus.PENDING.value,
    PayoutStatus.SUCCEEDED.value: TransactionStatus.SETTLED.value,
    PayoutStatus.FAILED.value: TransactionStatus.FAILED.value,
    PayoutStatus.REVERSED.value: TransactionStatus.FAILED.value,
    PayoutStatus.REJECTED.value: TransactionStatus.FAILED.value,
}


async def run(now=None) -> dict[str, Any]:
    """Settle stale open items with Paystack. Each item is its own transaction."""
    if not settings.payments_enabled:
        return {"skipped": "payments not configured"}
    now = now or utcnow()
    cutoff = now - timedelta(minutes=settings.RECONCILE_AFTER_MINUTES)
    results: dict[str, Any] = {"payments": {}, "payouts": {}, "errors": 0}
    async with session_scope() as db:
        payment_refs = (
            (
                await db.execute(
                    select(Payment.reference).where(
                        Payment.status == PaymentStatus.INITIALIZED.value, Payment.created_at < cutoff
                    )
                )
            )
            .scalars()
            .all()
        )
        payout_refs = (
            (
                await db.execute(
                    select(Payout.reference).where(
                        Payout.status.in_([PayoutStatus.PENDING.value, PayoutStatus.OTP_REQUIRED.value]),
                        Payout.updated_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        unconfirmed = (
            (
                await db.execute(
                    select(Payout.reference).where(
                        Payout.status.in_(
                            [PayoutStatus.SUCCEEDED.value, PayoutStatus.FAILED.value, PayoutStatus.REVERSED.value]
                        ),
                        Payout.transfer_code.is_not(None),
                        Payout.reconciled_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    for ref in payment_refs:
        async with session_scope() as db:
            payment = (await db.execute(select(Payment).where(Payment.reference == ref))).scalars().one()
            try:
                data = await paystack.verify_transaction(ref)
            except PaystackError as exc:
                if exc.status == 404 or "not found" in str(exc).lower():
                    data = {"status": "abandoned", "gateway_response": "Checkout was never completed"}
                else:
                    results["errors"] += 1
                    continue
            outcome = await payments_service.apply_paystack_result(db, payment, data, source="reconciliation")
            await db.commit()
            results["payments"][ref] = outcome
    for ref in [*payout_refs, *unconfirmed]:
        async with session_scope() as db:
            payout = (await db.execute(select(Payout).where(Payout.reference == ref))).scalars().one()
            try:
                data = await paystack.verify_transfer(ref)
            except PaystackError as exc:
                if (
                    exc.status == 404 or "not found" in str(exc).lower()
                ) and payout.status == PayoutStatus.PENDING.value:
                    # Paystack has no such transfer: it was never created, so the held funds go back.
                    data = {"status": "failed", "reason": "Transfer was not created at Paystack"}
                else:
                    results["errors"] += 1
                    continue
            outcome = await payments_service.apply_transfer_result(db, payout, data)
            await db.refresh(payout)
            remote = str(data.get("status") or "")
            local = {"success": "SUCCEEDED", "failed": "FAILED", "reversed": "REVERSED"}.get(remote)
            if local == payout.status:
                payout.reconciled_at = utcnow()
                outcome = f"{outcome}; reconciled"
            elif local and payout.status in HOLD_FOR and payout.status not in payments_service.OPEN_PAYOUT:
                outcome = f"MISMATCH: AgentMesh says {payout.status}, Paystack says {remote}"
                logger.error("Payout %s %s", ref, outcome)
            await db.commit()
            results["payouts"][ref] = outcome
    return results


async def report(db: AsyncSession) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    credits: dict[Any, Any] = {
        wallet: total
        for wallet, total in (
            await db.execute(
                select(Transaction.to_wallet, func.coalesce(func.sum(Transaction.amount), 0))
                .where(Transaction.to_wallet.is_not(None), Transaction.status == TransactionStatus.SETTLED.value)
                .group_by(Transaction.to_wallet)
            )
        ).all()
    }
    debits: dict[Any, Any] = {
        wallet: total
        for wallet, total in (
            await db.execute(
                select(Transaction.from_wallet, func.coalesce(func.sum(Transaction.amount), 0))
                .where(Transaction.from_wallet.is_not(None), Transaction.status.in_(DEBIT_STATES))
                .group_by(Transaction.from_wallet)
            )
        ).all()
    }
    wallets = (await db.execute(select(Wallet.id, Wallet.user_id, Wallet.balance))).all()
    for wallet_id, user_id, balance in wallets:
        expected = money(Decimal(credits.get(wallet_id, 0)) - Decimal(debits.get(wallet_id, 0)))
        if money(Decimal(balance or 0)) != expected:
            issues.append(
                {
                    "kind": "wallet_balance",
                    "wallet_id": str(wallet_id),
                    "user_id": str(user_id),
                    "balance": str(money(Decimal(balance or 0))),
                    "ledger": str(expected),
                }
            )

    posted = {
        (ref, t): Decimal(a)
        for ref, t, a in (
            await db.execute(
                select(Transaction.reference, Transaction.type, func.sum(Transaction.amount))
                .where(Transaction.reference.like("charge:%"))
                .group_by(Transaction.reference, Transaction.type)
            )
        ).all()
    }
    charges = (await db.execute(select(Charge))).scalars().all()
    for c in charges:
        key = f"charge:{c.id}"
        debit = posted.get((key, TransactionType.COMPUTE_CHARGE.value), Decimal(0))
        credit = posted.get((key, TransactionType.PROVIDER_CREDIT.value), Decimal(0))
        fee = posted.get((key, TransactionType.PLATFORM_FEE.value), Decimal(0))
        if (
            money(debit) != money(c.amount)
            or money(credit + fee) != money(debit)
            or money(c.provider_amount + c.platform_fee) != money(c.amount)
        ):
            issues.append(
                {
                    "kind": "charge_split",
                    "charge_id": str(c.id),
                    "amount": str(c.amount),
                    "debited": str(debit),
                    "credited": str(credit),
                    "fee": str(fee),
                }
            )

    deposits = {
        ref: (n, Decimal(a))
        for ref, n, a in (
            await db.execute(
                select(Transaction.reference, func.count(), func.sum(Transaction.amount))
                .where(Transaction.type == TransactionType.DEPOSIT.value, Transaction.reference.like("am-top-%"))
                .group_by(Transaction.reference)
            )
        ).all()
    }
    for p in (await db.execute(select(Payment))).scalars().all():
        n, amount = deposits.get(p.reference, (0, Decimal(0)))
        if p.status == PaymentStatus.SUCCEEDED.value and (n != 1 or money(amount) != money(p.amount)):
            issues.append({"kind": "payment_not_credited_once", "reference": p.reference, "deposits": n})
        if p.status != PaymentStatus.SUCCEEDED.value and n:
            issues.append({"kind": "deposit_without_success", "reference": p.reference, "status": p.status})
        if p.status == PaymentStatus.REVIEW.value:
            issues.append({"kind": "payment_needs_review", "reference": p.reference, "reason": p.failure_reason})

    for po in (await db.execute(select(Payout))).scalars().all():
        hold = await db.get(Transaction, po.transaction_id) if po.transaction_id else None
        want = HOLD_FOR.get(po.status)
        if hold is None or hold.status != want or money(Decimal(hold.amount)) != money(Decimal(po.amount)):
            issues.append(
                {
                    "kind": "payout_hold",
                    "reference": po.reference,
                    "status": po.status,
                    "hold_status": hold.status if hold else None,
                }
            )

    open_counts = {
        "payments_initialized": int(
            (await db.execute(select(func.count()).where(Payment.status == PaymentStatus.INITIALIZED.value))).scalar()
            or 0
        ),
        "payouts_awaiting_approval": int(
            (await db.execute(select(func.count()).where(Payout.status == PayoutStatus.REQUESTED.value))).scalar() or 0
        ),
        "payouts_in_flight": int(
            (
                await db.execute(
                    select(func.count()).where(
                        Payout.status.in_([PayoutStatus.PENDING.value, PayoutStatus.OTP_REQUIRED.value])
                    )
                )
            ).scalar()
            or 0
        ),
    }
    return {
        "ok": not issues,
        "issues": issues,
        "checked": {"wallets": len(wallets), "charges": len(charges)},
        "open": open_counts,
        "generated_at": utcnow(),
    }
