"""Read-only aggregates for dashboards: usage summaries (customer, provider, operator), the operator overview,
and the public network figures shown on the landing page.

Everything here is computed from stored records. Token counts are summed only where the runtime reported them;
requests without counts are reported separately and never estimated.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timeutil import utcnow
from app.models.deployment import Deployment, DeploymentStatus
from app.models.model import Model, ModelArtifact
from app.models.node import Node, NodeStatus
from app.models.transaction import Transaction
from app.models.usage import UsageRecord
from app.models.user import Customer, Provider, User

# Nodes the scheduler may consider (see scheduler_service); used for "online" counts.
ONLINE_NODE_STATUSES = (NodeStatus.ONLINE.value, NodeStatus.AVAILABLE.value, NodeStatus.BUSY.value)


def _usage_columns() -> list:
    return [
        func.count(UsageRecord.id).label("requests"),
        func.coalesce(func.sum(case((UsageRecord.outcome == "success", 1), else_=0)), 0).label("succeeded"),
        func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(case((UsageRecord.output_tokens.is_(None), 1), else_=0)), 0).label("unreported"),
    ]


def _usage_row(row: Any) -> dict[str, int]:
    requests = int(row.requests or 0)
    succeeded = int(row.succeeded or 0)
    return {
        "requests": requests,
        "succeeded": succeeded,
        "failed": requests - succeeded,
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
        "requests_without_token_counts": int(row.unreported or 0),
    }


async def usage_summary(db: AsyncSession, user: User, days: int, scope: str) -> dict[str, Any]:
    """Inference usage over the last ``days`` days for the caller's ``scope``: "customer" (their deployments),
    "provider" (requests served by their nodes) or "network" (everything; staff only, checked by the caller)."""
    since = utcnow() - timedelta(days=days)
    base: Select = select().where(UsageRecord.kind == "inference", UsageRecord.created_at >= since)
    if scope == "customer":
        owned = select(Deployment.id).join(Customer, Deployment.customer_id == Customer.id)
        base = base.where(UsageRecord.deployment_id.in_(owned.where(Customer.user_id == user.id)))
    elif scope == "provider":
        owned = select(Node.id).join(Provider, Node.owner_id == Provider.id)
        base = base.where(UsageRecord.node_id.in_(owned.where(Provider.user_id == user.id)))

    totals = (await db.execute(base.add_columns(*_usage_columns()))).one()
    day = func.date(UsageRecord.created_at)
    per_day = (
        await db.execute(base.add_columns(day.label("day"), *_usage_columns()).group_by(day).order_by(day))
    ).all()
    per_dep = (
        await db.execute(
            base.add_columns(UsageRecord.deployment_id, *_usage_columns())
            .group_by(UsageRecord.deployment_id)
            .order_by(func.count(UsageRecord.id).desc())
            .limit(50)
        )
    ).all()
    return {
        "scope": scope,
        "days": days,
        "since": since,
        "totals": _usage_row(totals),
        "by_day": [{"date": str(r.day), **_usage_row(r)} for r in per_day],
        "by_deployment": [{"deployment_id": r.deployment_id, **_usage_row(r)} for r in per_dep if r.deployment_id],
        "token_source": "runtime_reported",
    }


async def _count_by(db: AsyncSession, column, *where) -> dict[str, int]:
    rows = (await db.execute(select(column, func.count()).where(*where).group_by(column))).all()
    return {str(getattr(k, "value", k)): int(n) for k, n in rows if k is not None}


async def _deployable_models(db: AsyncSession) -> int:
    has_artifact = select(ModelArtifact.model_id).where(ModelArtifact.is_enabled.is_(True))
    query = select(func.count(Model.id)).where(Model.is_approved.is_(True), Model.id.in_(has_artifact))
    return int((await db.execute(query)).scalar() or 0)


async def public_stats(db: AsyncSession) -> dict[str, Any]:
    """Counts only: no node names, owners, locations, or hardware details."""
    online = (
        await db.execute(
            select(Node.runtimes, Node.allocated_vram_mb).where(
                Node.status.in_(ONLINE_NODE_STATUSES), Node.accepting_workloads.is_(True)
            )
        )
    ).all()
    runtimes = sorted(
        {
            str(r["name"])
            for rts, _ in online
            for r in (rts or [])
            if isinstance(r, dict) and r.get("available") and r.get("name")
        }
    )
    ready = await db.execute(select(func.count(Deployment.id)).where(Deployment.status == DeploymentStatus.READY))
    return {
        "nodes_online": len(online),
        "gpu_nodes_online": sum(1 for _, vram in online if (vram or 0) > 0),
        "runtimes_online": runtimes,
        "models_deployable": await _deployable_models(db),
        "deployments_ready": int(ready.scalar() or 0),
        "features": {
            "test_credits": settings.test_credits_enabled,
            "payments": False,
            "provider_payouts": False,
            "confidential_computing": False,
        },
        "generated_at": utcnow(),
    }


async def operator_overview(db: AsyncSession) -> dict[str, Any]:
    since = utcnow() - timedelta(hours=24)
    usage = (
        await db.execute(
            select(*_usage_columns()).where(UsageRecord.kind == "inference", UsageRecord.created_at >= since)
        )
    ).one()
    ledger = (
        await db.execute(
            select(
                Transaction.type, Transaction.status, func.count(), func.coalesce(func.sum(Transaction.amount), 0)
            ).group_by(Transaction.type, Transaction.status)
        )
    ).all()
    stale_cutoff = utcnow() - timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS)
    stale = await db.execute(
        select(func.count(Node.id)).where(Node.status.in_(ONLINE_NODE_STATUSES), Node.last_heartbeat < stale_cutoff)
    )
    return {
        "nodes_by_status": await _count_by(db, Node.status),
        "nodes_paused": int(
            (await db.execute(select(func.count(Node.id)).where(Node.accepting_workloads.is_(False)))).scalar() or 0
        ),
        "nodes_heartbeat_overdue": int(stale.scalar() or 0),
        "deployments_by_status": await _count_by(db, Deployment.status, Deployment.deleted_at.is_(None)),
        "deployments_by_runtime": await _count_by(db, Deployment.runtime, Deployment.status == DeploymentStatus.READY),
        "models": {
            "total": int((await db.execute(select(func.count(Model.id)))).scalar() or 0),
            "approved": int(
                (await db.execute(select(func.count(Model.id)).where(Model.is_approved.is_(True)))).scalar() or 0
            ),
            "deployable": await _deployable_models(db),
        },
        "users_by_role": await _count_by(db, User.role),
        "usage_24h": _usage_row(usage),
        "ledger": [
            {
                "type": str(getattr(t, "value", t)),
                "status": str(getattr(s, "value", s)),
                "count": int(n),
                "amount": str(amount),
            }
            for t, s, n, amount in ledger
        ],
        "generated_at": utcnow(),
    }


async def list_nodes_with_owner(db: AsyncSession, status: str | None, limit: int) -> list[tuple[Node, str | None]]:
    query = (
        select(Node, User.email)
        .join(Provider, Node.owner_id == Provider.id)
        .join(User, Provider.user_id == User.id)
        .order_by(Node.created_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Node.status == status)
    return [(n, e) for n, e in (await db.execute(query)).all()]


async def list_deployments_with_owner(
    db: AsyncSession, status: str | None, node_id: uuid.UUID | None, limit: int
) -> list[tuple[Deployment, str | None]]:
    query = (
        select(Deployment, User.email)
        .outerjoin(Customer, Deployment.customer_id == Customer.id)
        .outerjoin(User, Customer.user_id == User.id)
        .order_by(Deployment.created_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Deployment.status == status)
    if node_id:
        query = query.where(Deployment.node_id == node_id)
    return [(d, e) for d, e in (await db.execute(query)).all()]
