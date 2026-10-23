"""Periodic reconciliation. Each ``run_*`` function is a single pass and is safe to run repeatedly."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import session_scope
from app.core.timeutil import utcnow
from app.models.deployment import Deployment
from app.models.deployment import DeploymentStatus as S
from app.models.node import Node, NodeStatus
from app.models.worker import CommandStatus, CommandType, NodeCommand
from app.services import deployment_lifecycle as lifecycle
from app.services import placement_service
from app.services.scheduler_service import release_reservation

logger = logging.getLogger(__name__)

PROVISIONING_STATES = (S.SCHEDULED.value, S.PROVISIONING.value, S.STARTING.value)


async def _fail(db, dep: Deployment, code: str, message: str, *, cleanup: bool) -> None:
    """Move the deployment to another node when the failure is the node's fault, otherwise fail it."""
    await placement_service.fail_or_reschedule(
        db, dep, code=code, message=message, actor="system", cleanup_old_node=cleanup
    )


async def handle_node_loss(db, node: Node, reason: str) -> None:
    """A node went away. Deployments still provisioning there move immediately; serving deployments become
    UNHEALTHY and move only if the node does not come back within UNHEALTHY_GRACE_SECONDS. Does not commit."""
    deps = (
        (
            await db.execute(
                select(Deployment).where(
                    Deployment.node_id == node.id,
                    Deployment.status.in_([*PROVISIONING_STATES, S.READY.value]),
                )
            )
        )
        .scalars()
        .all()
    )
    for dep in deps:
        if dep.status == S.READY.value:
            await lifecycle.transition(db, dep, S.UNHEALTHY, actor="system", message=reason)
        else:
            await _fail(db, dep, "NODE_OFFLINE", reason, cleanup=True)


async def run_stale_nodes(now: datetime | None = None) -> int:
    """Mark nodes without a recent heartbeat OFFLINE (see handle_node_loss). Reservations of serving
    deployments are kept during the grace period so a brief disconnection cannot double-book the node."""
    now = now or utcnow()
    cutoff = now - timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS)
    async with session_scope() as db:
        nodes = (
            (
                await db.execute(
                    select(Node).where(
                        Node.status == NodeStatus.ONLINE.value,
                        Node.mode.is_not(None),
                        Node.last_heartbeat < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for node in nodes:
            node.status = NodeStatus.OFFLINE.value
            await handle_node_loss(db, node, "Node stopped sending heartbeats")
        await db.commit()
        return len(nodes)


async def run_deployment_timeouts(now: datetime | None = None) -> int:
    now = now or utcnow()
    changed = 0
    async with session_scope() as db:
        deps = (await db.execute(select(Deployment).where(Deployment.status.in_(PROVISIONING_STATES)))).scalars().all()
        for dep in deps:
            last_progress = dep.updated_at or dep.created_at
            if now - dep.created_at > timedelta(seconds=settings.PROVISION_MAX_SECONDS):
                await _fail(
                    db, dep, "PROVISION_TIMEOUT", "Provisioning exceeded the maximum allowed time", cleanup=True
                )
                changed += 1
            elif now - last_progress > timedelta(seconds=settings.PROVISION_STALL_TIMEOUT_SECONDS):
                await _fail(db, dep, "PROVISION_STALLED", "No provisioning progress reported by the node", cleanup=True)
                changed += 1

        stopping = (await db.execute(select(Deployment).where(Deployment.status == S.STOPPING.value))).scalars().all()
        for dep in stopping:
            if now - (dep.updated_at or dep.created_at) > timedelta(seconds=settings.STOP_TIMEOUT_SECONDS):
                final = S.STOPPED if dep.was_ready else S.CANCELLED
                msg = "Stop not confirmed by the node; it will be told to clean up when it reconnects"
                if await lifecycle.transition(db, dep, final, actor="system", message=msg):
                    dep.cleanup_status = "pending_node"
                    await release_reservation(db, dep.id)
                    changed += 1

        unhealthy = (await db.execute(select(Deployment).where(Deployment.status == S.UNHEALTHY.value))).scalars().all()
        for dep in unhealthy:
            if now - (dep.updated_at or dep.created_at) > timedelta(seconds=settings.UNHEALTHY_GRACE_SECONDS):
                await _fail(db, dep, "UNHEALTHY_TIMEOUT", "Deployment stayed unhealthy", cleanup=True)
                changed += 1
        await db.commit()
    return changed


async def run_command_leases(now: datetime | None = None) -> int:
    """Give up on commands whose final lease expired. A DEPLOY that was never acknowledged fails its
    deployment; a STOP that was never acknowledged is left to the stop timeout above."""
    now = now or utcnow()
    async with session_scope() as db:
        cmds = (
            (
                await db.execute(
                    select(NodeCommand).where(
                        NodeCommand.status == CommandStatus.LEASED.value,
                        NodeCommand.lease_expires_at < now,
                        NodeCommand.attempts >= NodeCommand.max_attempts,
                    )
                )
            )
            .scalars()
            .all()
        )
        for cmd in cmds:
            cmd.status = CommandStatus.FAILED.value
            cmd.error = "Lease expired after maximum delivery attempts"
            cmd.completed_at = now
            if cmd.type == CommandType.DEPLOY.value and cmd.deployment_id:
                dep = await db.get(Deployment, cmd.deployment_id)
                if dep and dep.status in PROVISIONING_STATES:
                    await _fail(
                        db, dep, "NODE_UNRESPONSIVE", "The node did not acknowledge the deployment", cleanup=False
                    )
        await db.commit()
        return len(cmds)


async def _is_leader(redis, owner: str) -> bool:
    """With several API replicas, one runs the monitors per round (their writes are conflict-safe anyway)."""
    if redis is None:
        return True
    key = "monitors:leader"
    ttl = max(5, settings.MONITOR_INTERVAL_SECONDS * 2)
    if await redis.set(key, owner, nx=True, ex=ttl):
        return True
    if await redis.get(key) == owner:
        await redis.expire(key, ttl)
        return True
    return False


RECONCILE_EVERY_SECONDS = 600


async def monitor_loop(redis=None) -> None:
    from app.services import billing_service, reconciliation_service
    from app.services.ai import workflow as ai_workflow

    owner = uuid.uuid4().hex
    last_billing = last_reconcile = 0.0
    while True:
        await asyncio.sleep(settings.MONITOR_INTERVAL_SECONDS)
        try:
            if not await _is_leader(redis, owner):
                continue
        except Exception:  # noqa: BLE001
            logger.exception("Monitor leader election failed")
            continue
        jobs: list[Callable[[], Awaitable[Any]]] = [
            run_stale_nodes,
            run_command_leases,
            run_deployment_timeouts,
            ai_workflow.run_due,  # deterministic steps; needs no inference machine to be online
        ]
        now = time.monotonic()
        if now - last_billing >= settings.BILLING_INTERVAL_SECONDS:
            jobs.append(billing_service.run_billing)
            last_billing = now
        if settings.payments_enabled and now - last_reconcile >= RECONCILE_EVERY_SECONDS:
            jobs.append(reconciliation_service.run)
            last_reconcile = now
        for job in jobs:
            try:
                await job()
            except Exception:  # noqa: BLE001
                logger.exception("Background job %s failed", job.__name__)
