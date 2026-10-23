"""Pricing and rating: turns measured usage into charges and ledger postings.

What is charged, per deployment and node:

* READY time x reserved resources (CPU cores, RAM, VRAM) at the pricing version in force. READY intervals come
  from the control plane's own lifecycle events, not from the worker. UNHEALTHY time is not charged.
* Input/output tokens at the per-million prices. Counts are runtime-reported (see UsageRecord.token_source);
  requests without counts are not charged for tokens.

A background job rates each deployment's window [metered_until, now) at most every BILLING_INTERVAL_SECONDS,
splitting at pricing-version boundaries and node changes. Each (deployment, node, period_start) produces at most
one Charge (unique constraint) and advances the watermark with a compare-and-set, so concurrent replicas cannot
double-charge. Settlement debits the customer, credits the provider, and records the platform fee; the
customer's balance may go below zero by at most one window, after which their deployments are stopped.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import session_scope
from app.core.db_utils import rowcount
from app.core.timeutil import utcnow
from app.models.billing import Charge, PricingRule
from app.models.deployment import Deployment, DeploymentEvent
from app.models.deployment import DeploymentStatus as S
from app.models.node import Node
from app.models.reservation import ResourceReservation
from app.models.transaction import TransactionType
from app.models.usage import UsageRecord
from app.models.user import Customer, Provider, User
from app.services import audit_service, ledger_service
from app.services.ledger_service import money

logger = logging.getLogger(__name__)

MB_PER_GB = Decimal(1024)
SECONDS_PER_HOUR = Decimal(3600)
MILLION = Decimal(1_000_000)


# --- Pricing rules -----------------------------------------------------------------------------------------


async def active_rule(db: AsyncSession, at: datetime | None = None) -> PricingRule | None:
    at = at or utcnow()
    query = (
        select(PricingRule)
        .where(PricingRule.effective_from <= at)
        .order_by(PricingRule.effective_from.desc(), PricingRule.version.desc())
        .limit(1)
    )
    return (await db.execute(query)).scalars().first()


async def list_rules(db: AsyncSession) -> list[PricingRule]:
    return list((await db.execute(select(PricingRule).order_by(PricingRule.version.desc()))).scalars().all())


async def create_rule(db: AsyncSession, data: dict, actor: User) -> PricingRule:
    """Add a new pricing version. Versions are immutable and cannot take effect in the past, so charges
    already rated are never re-priced."""
    now = utcnow()
    effective = data.pop("effective_from", None) or now
    if effective.tzinfo is not None:
        effective = effective.astimezone(UTC).replace(tzinfo=None)
    if effective < now - timedelta(seconds=60):
        raise HTTPException(status_code=422, detail="effective_from cannot be in the past")
    latest = (await db.execute(select(func.max(PricingRule.version)))).scalar() or 0
    rule = PricingRule(
        id=uuid.uuid4(),
        version=latest + 1,
        currency=settings.BILLING_CURRENCY,
        effective_from=max(effective, now),
        created_by=actor.id,
        **data,
    )
    db.add(rule)
    audit_service.record(
        db,
        actor_id=actor.id,
        action="pricing.version_created",
        resource_type="pricing_rule",
        resource_id=rule.id,
        details={"version": rule.version, **{k: str(v) for k, v in data.items()}},
    )
    await db.commit()
    await db.refresh(rule)
    return rule


def hourly_resource_price(rule: PricingRule, cpu_cores: int, ram_mb: int, vram_mb: int) -> Decimal:
    return (
        Decimal(rule.cpu_core_hour) * cpu_cores
        + Decimal(rule.ram_gb_hour) * Decimal(ram_mb) / MB_PER_GB
        + Decimal(rule.vram_gb_hour) * Decimal(vram_mb) / MB_PER_GB
    )


def is_free(rule: PricingRule | None) -> bool:
    return rule is None or not any(
        Decimal(v)
        for v in (
            rule.cpu_core_hour,
            rule.ram_gb_hour,
            rule.vram_gb_hour,
            rule.input_tokens_per_million,
            rule.output_tokens_per_million,
        )
    )


async def require_prepaid(db: AsyncSession, user_id: uuid.UUID, cpu_cores: int, ram_mb: int, vram_mb: int) -> None:
    """Refuse a deployment the customer cannot afford for BILLING_MIN_PREPAID_HOURS of its reservation."""
    rule = await active_rule(db)
    if is_free(rule):
        return
    assert rule is not None
    hours = Decimal(str(settings.BILLING_MIN_PREPAID_HOURS))
    needed = money(hourly_resource_price(rule, cpu_cores, ram_mb, vram_mb) * hours)
    wallet = await ledger_service.wallet_for_user(db, user_id)
    have = await ledger_service.balance(db, wallet.id)
    if have < needed or have <= 0:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "insufficient_balance",
                "message": f"This deployment needs at least {needed} {rule.currency} in your wallet "
                f"({settings.BILLING_MIN_PREPAID_HOURS:g} h of its reserved resources); you have {money(have)}.",
                "required": str(needed),
                "balance": str(money(have)),
                "currency": rule.currency,
            },
        )


# --- Measurement -------------------------------------------------------------------------------------------


@dataclass
class Interval:
    start: datetime
    end: datetime
    node_id: uuid.UUID | None


def ready_intervals(events: list[DeploymentEvent], now: datetime, fallback_node: uuid.UUID | None) -> list[Interval]:
    """READY periods from the lifecycle history (state changes only, in time order)."""
    out: list[Interval] = []
    opened: tuple[datetime, uuid.UUID | None] | None = None
    for e in events:
        if e.to_status is None:
            continue  # progress note
        if e.to_status == S.READY.value and opened is None:
            opened = (e.created_at, e.node_id or fallback_node)
        elif e.to_status != S.READY.value and opened is not None:
            out.append(Interval(opened[0], e.created_at, opened[1]))
            opened = None
    if opened is not None:
        out.append(Interval(opened[0], now, opened[1]))
    return out


def _clip(intervals: list[Interval], start: datetime, end: datetime) -> dict[uuid.UUID | None, float]:
    seconds: dict[uuid.UUID | None, float] = {}
    for iv in intervals:
        lo, hi = max(iv.start, start), min(iv.end, end)
        if hi > lo:
            seconds[iv.node_id] = seconds.get(iv.node_id, 0.0) + (hi - lo).total_seconds()
    return seconds


async def _tokens(db: AsyncSession, dep_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    rows = (
        await db.execute(
            select(
                UsageRecord.node_id,
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                # Output tokens are reported by the provider's runtime. Bound them by the response bytes the
                # gateway itself counted (every token costs at least one byte), so they cannot be inflated freely.
                func.coalesce(
                    func.sum(
                        case(
                            (
                                UsageRecord.response_bytes.is_not(None)
                                & (UsageRecord.output_tokens > UsageRecord.response_bytes),
                                UsageRecord.response_bytes,
                            ),
                            else_=UsageRecord.output_tokens,
                        )
                    ),
                    0,
                ),
            )
            .where(
                UsageRecord.deployment_id == dep_id,
                UsageRecord.kind == "inference",
                UsageRecord.created_at >= start,
                UsageRecord.created_at < end,
            )
            .group_by(UsageRecord.node_id)
        )
    ).all()
    return {node: (int(i), int(o)) for node, i, o in rows}


async def _reservation(db: AsyncSession, dep_id: uuid.UUID, node_id: uuid.UUID | None) -> tuple[int, int, int]:
    if node_id is None:
        return 0, 0, 0
    res = (
        (
            await db.execute(
                select(ResourceReservation)
                .where(ResourceReservation.deployment_id == dep_id, ResourceReservation.node_id == node_id)
                .order_by(ResourceReservation.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return (res.cpu_cores, res.ram_mb, res.vram_mb) if res else (0, 0, 0)


async def _provider_user(db: AsyncSession, node_id: uuid.UUID | None) -> uuid.UUID | None:
    if node_id is None:
        return None
    return (
        await db.execute(select(Provider.user_id).join(Node, Node.owner_id == Provider.id).where(Node.id == node_id))
    ).scalar()


# --- Rating ------------------------------------------------------------------------------------------------


def price(rule: PricingRule, ready_seconds: float, cpu: int, ram_mb: int, vram_mb: int, tin: int, tout: int):
    hours = Decimal(str(ready_seconds)) / SECONDS_PER_HOUR
    resource = money(hourly_resource_price(rule, cpu, ram_mb, vram_mb) * hours)
    tokens = money(
        (Decimal(rule.input_tokens_per_million) * tin + Decimal(rule.output_tokens_per_million) * tout) / MILLION
    )
    amount = resource + tokens
    fee = money(amount * Decimal(rule.platform_fee_rate))
    return resource, tokens, amount, amount - fee, fee


async def _rules_in(db: AsyncSession, start: datetime, end: datetime) -> list[tuple[datetime, PricingRule | None]]:
    """(segment start, rule) for each pricing segment of [start, end)."""
    later = (
        (
            await db.execute(
                select(PricingRule)
                .where(PricingRule.effective_from > start, PricingRule.effective_from < end)
                .order_by(PricingRule.effective_from)
            )
        )
        .scalars()
        .all()
    )
    segments: list[tuple[datetime, PricingRule | None]] = [(start, await active_rule(db, start))]
    segments += [(r.effective_from, r) for r in later]
    return segments


async def rate_deployment(db: AsyncSession, dep: Deployment, now: datetime) -> list[Charge]:
    """Rate [metered_until, now) for one deployment and settle it. Does not commit; raises on a lost race."""
    start = dep.metered_until or dep.created_at
    events = list(
        (
            await db.execute(
                select(DeploymentEvent)
                .where(DeploymentEvent.deployment_id == dep.id, DeploymentEvent.to_status.is_not(None))
                .order_by(DeploymentEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    intervals = ready_intervals(events, now, dep.node_id)
    customer_user = (await db.execute(select(Customer.user_id).where(Customer.id == dep.customer_id))).scalar()
    charges: list[Charge] = []
    segments = await _rules_in(db, start, now)
    for i, (seg_start, rule) in enumerate(segments):
        seg_end = segments[i + 1][0] if i + 1 < len(segments) else now
        if rule is None or customer_user is None:
            continue  # no price in force: usage is measured but free
        seconds = _clip(intervals, seg_start, seg_end)
        tokens = await _tokens(db, dep.id, seg_start, seg_end)
        for node_id in set(seconds) | set(tokens):
            ready_s = seconds.get(node_id, 0.0)
            tin, tout = tokens.get(node_id, (0, 0))
            cpu, ram, vram = await _reservation(db, dep.id, node_id)
            resource, token_amt, amount, provider_amt, fee = price(rule, ready_s, cpu, ram, vram, tin, tout)
            if amount <= 0:
                continue
            customer_wallet = await ledger_service.wallet_for_user(db, customer_user)
            provider_user = await _provider_user(db, node_id)
            provider_wallet = await ledger_service.wallet_for_user(db, provider_user) if provider_user else None
            charge = Charge(
                id=uuid.uuid4(),
                deployment_id=dep.id,
                node_id=node_id,
                customer_wallet_id=customer_wallet.id,
                provider_wallet_id=provider_wallet.id if provider_wallet else None,
                pricing_rule_id=rule.id,
                period_start=seg_start,
                period_end=seg_end,
                ready_seconds=round(ready_s, 3),
                cpu_cores=cpu,
                ram_mb=ram,
                vram_mb=vram,
                input_tokens=tin,
                output_tokens=tout,
                resource_amount=resource,
                token_amount=token_amt,
                amount=amount,
                provider_amount=provider_amt if provider_wallet else money(0),
                platform_fee=fee if provider_wallet else amount,
                currency=rule.currency,
            )
            db.add(charge)
            await db.flush()
            await _settle_charge(db, charge, customer_wallet, provider_wallet)
            charges.append(charge)
    moved = await db.execute(
        update(Deployment)
        .where(
            Deployment.id == dep.id,
            Deployment.metered_until.is_(None) if dep.metered_until is None else Deployment.metered_until == start,
        )
        .values(metered_until=now)
        .execution_options(synchronize_session=False)
    )
    if rowcount(moved) != 1:
        raise RuntimeError(f"Billing watermark for deployment {dep.id} moved concurrently")
    dep.metered_until = now
    return charges


async def _settle_charge(db: AsyncSession, charge: Charge, customer_wallet, provider_wallet) -> None:
    key = f"charge:{charge.id}"
    period = f"{charge.period_start:%Y-%m-%d %H:%M}-{charge.period_end:%H:%M} UTC"
    await ledger_service.post(
        db,
        key=f"{key}:debit",
        type=TransactionType.COMPUTE_CHARGE,
        amount=charge.amount,
        from_wallet=customer_wallet,
        reference=key,
        deployment_id=charge.deployment_id,
        description=f"Deployment usage {period}",
    )
    if provider_wallet is not None and charge.provider_amount > 0:
        await ledger_service.post(
            db,
            key=f"{key}:provider",
            type=TransactionType.PROVIDER_CREDIT,
            amount=charge.provider_amount,
            to_wallet=provider_wallet,
            reference=key,
            deployment_id=charge.deployment_id,
            description=f"Hosting {period}",
        )
    await ledger_service.post(
        db,
        key=f"{key}:fee",
        type=TransactionType.PLATFORM_FEE,
        amount=charge.platform_fee,
        reference=key,
        deployment_id=charge.deployment_id,
        description="Platform fee",
    )


async def _stop_if_exhausted(db: AsyncSession, customer_wallet_id: uuid.UUID) -> int:
    """Stop a customer's running deployments once their prepaid balance is used up."""
    from app.models.wallet import Wallet
    from app.services import deployment_lifecycle as lifecycle
    from app.services.deployment_service import _stop

    wallet = await db.get(Wallet, customer_wallet_id)
    remaining = await ledger_service.balance(db, customer_wallet_id)  # balances move in SQL, not on the ORM object
    if wallet is None or remaining > 0:
        return 0
    deps = (
        (
            await db.execute(
                select(Deployment)
                .join(Customer, Deployment.customer_id == Customer.id)
                .where(
                    Customer.user_id == wallet.user_id,
                    Deployment.status.in_([s.value for s in lifecycle.ACTIVE if s != S.STOPPING]),
                )
            )
        )
        .scalars()
        .all()
    )
    for dep in deps:
        await _stop(db, dep, actor="system", message="Stopped: the wallet balance is used up. Top up to deploy again.")
        dep.error_code = "INSUFFICIENT_FUNDS"
        dep.error_message = "The wallet balance is used up"
        audit_service.record(
            db,
            actor_id=None,
            action="deployment.stopped_insufficient_funds",
            resource_type="deployment",
            resource_id=dep.id,
            details={"balance": str(money(remaining))},
        )
    return len(deps)


async def due_deployments(db: AsyncSession, now: datetime) -> list[Deployment]:
    rows = (
        (
            await db.execute(
                select(Deployment).where(
                    Deployment.was_ready.is_(True),
                    or_(
                        Deployment.metered_until.is_(None),
                        Deployment.ended_at.is_(None),
                        Deployment.metered_until < Deployment.ended_at,
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    interval = timedelta(seconds=settings.BILLING_INTERVAL_SECONDS)
    return [d for d in rows if d.ended_at is not None or now - (d.metered_until or d.created_at) >= interval]


async def run_billing(now: datetime | None = None) -> int:
    """Rate every deployment that is due. Each deployment is its own transaction. Returns charges created."""
    now = now or utcnow()
    created = 0
    async with session_scope() as db:
        ids = [d.id for d in await due_deployments(db, now)]
    for dep_id in ids:
        async with session_scope() as db:
            dep = await db.get(Deployment, dep_id)
            if dep is None:
                continue
            try:
                charges = await rate_deployment(db, dep, now)
                for wallet_id in {c.customer_wallet_id for c in charges}:
                    await _stop_if_exhausted(db, wallet_id)
                await db.commit()
                created += len(charges)
            except Exception:  # noqa: BLE001 - one bad deployment must not stop billing for the rest
                await db.rollback()
                logger.exception("Billing failed for deployment %s", dep_id)
    return created
