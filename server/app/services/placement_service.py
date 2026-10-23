"""Placement decisions after something goes wrong: move a deployment to another node, or fail it.

A deployment keeps its id, endpoint, and API keys when it moves, so customers do not need to change anything.
Only failures caused by the node are retried elsewhere. Failures caused by the model (bad tag, failed test
generation, download error after the worker's own retries) are not, because another node would fail the
same way.
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timeutil import utcnow
from app.models.deployment import Deployment
from app.models.deployment import DeploymentStatus as S
from app.models.model import Model, ModelArtifact
from app.models.node import Node, NodeStatus
from app.models.worker import CommandType
from app.services import audit_service
from app.services import deployment_lifecycle as lifecycle
from app.services.catalog_service import (
    DeploymentConfig,
    ResourceRequest,
    estimate_requirements,
    is_unreviewed,
    worker_source,
)
from app.services.commands import cancel_undelivered, enqueue_command
from app.services.scheduler_service import NoEligibleNode, node_is_fresh, release_reservation, schedule

logger = logging.getLogger(__name__)

# Failure codes that are the node's fault and worth retrying on a different node.
RESCHEDULABLE_CODES = frozenset(
    {
        "NODE_UNRESPONSIVE",  # never picked up the deploy command
        "NODE_OFFLINE",  # stopped heartbeating while provisioning
        "NODE_REVOKED",
        "PROVISION_STALLED",
        "UNHEALTHY_TIMEOUT",
        "INSUFFICIENT_MEMORY",
        "INSUFFICIENT_DISK",
        "RUNTIME_START_FAILED",
        "RUNTIME_IMAGE_UNAVAILABLE",
        "MODEL_PULL_STALLED",
        "WORKLOAD_EXITED",
        "NODE_UNAVAILABLE",  # provider paused/drained the machine locally or its schedule ended
        "RUNTIME_UNAVAILABLE",  # the node no longer offers the runtime (stale capabilities)
        "WORKER_ERROR",  # unexpected worker failure: another node may not hit it (placements are bounded)
    }
)


async def artifact_for(db: AsyncSession, dep: Deployment) -> ModelArtifact:
    artifact = await db.get(ModelArtifact, dep.artifact_id) if dep.artifact_id else None
    if artifact is None:  # deployments created before artifacts existed
        artifact = (
            await db.execute(
                select(ModelArtifact).where(
                    ModelArtifact.model_id == dep.model_id, ModelArtifact.runtime == dep.runtime
                )
            )
        ).scalar_one_or_none()
    if artifact is None:
        raise ValueError(f"Deployment {dep.id} has no runtime artifact")
    return artifact


async def requirements_for(db: AsyncSession, dep: Deployment) -> ResourceRequest:
    model = await db.get(Model, dep.model_id)
    return estimate_requirements(
        await artifact_for(db, dep),
        DeploymentConfig(**(dep.config or {})),
        community=model is not None and is_unreviewed(model),
    )


def deploy_payload(dep: Deployment, req: ResourceRequest, source: dict | None = None) -> dict[str, Any]:
    """The only information sent to a worker: validated identifiers, a pinned model source, and limits. No
    customer credentials and no free-form runtime arguments."""
    return {
        "deployment_id": str(dep.id),
        "runtime": dep.runtime,
        "model_tag": dep.model_tag,
        "source": source,
        "num_ctx": (dep.config or {}).get("num_ctx", 2048),
        "resources": {
            "cpu_cores": req.cpu_cores,
            "ram_mb": req.ram_mb,
            "disk_mb": req.disk_mb,
            "vram_mb": req.vram_mb,
            "gpu": req.gpu_required,
        },
        "timeouts": {
            "stall_seconds": settings.PROVISION_STALL_TIMEOUT_SECONDS,
            "max_seconds": settings.PROVISION_MAX_SECONDS,
        },
    }


async def _stop_on_old_node(db: AsyncSession, dep: Deployment, node_id: uuid.UUID) -> None:
    # If the old node never received the deploy, there is nothing to clean up there.
    if not await cancel_undelivered(db, dep.id, CommandType.DEPLOY):
        await enqueue_command(db, node_id, dep.id, CommandType.STOP, {"deployment_id": str(dep.id)})


async def fail_or_reschedule(
    db: AsyncSession,
    dep: Deployment,
    *,
    code: str,
    message: str,
    actor: str,
    cleanup_old_node: bool,
) -> bool:
    """Handle a failure. Returns True if the deployment was moved to another node, False if it FAILED.
    Releases the old reservation either way. Does not commit."""
    status = S(dep.status)
    if status in lifecycle.TERMINAL:
        return False
    old_node = dep.node_id
    await release_reservation(db, dep.id)

    movable = (
        code in RESCHEDULABLE_CODES
        and status in (S.SCHEDULED, S.PROVISIONING, S.STARTING, S.READY, S.UNHEALTHY)
        and dep.deleted_at is None
        and dep.schedule_attempts < settings.MAX_SCHEDULE_ATTEMPTS
    )
    if movable:
        excluded = {uuid.UUID(str(n)) for n in (dep.excluded_node_ids or [])}
        if old_node:
            excluded.add(old_node)
        req = await requirements_for(db, dep)
        source = worker_source(await artifact_for(db, dep))
        try:
            node = await schedule(db, dep.id, req, exclude=excluded)
        except NoEligibleNode as exc:
            message = f"{message}. No other node could take it: {exc.evaluation.explain()}"
        else:
            if old_node and cleanup_old_node:
                await _stop_on_old_node(db, dep, old_node)
            note = f"{message}. Moved to another node (placement {dep.schedule_attempts + 1})"
            fields: dict[str, Any] = {
                "node_id": node.id,
                "schedule_attempts": dep.schedule_attempts + 1,
                "excluded_node_ids": sorted(str(n) for n in excluded),
                "error_code": code,
                "error_message": message,
            }
            if status == S.READY:
                # Serving deployments pass through UNHEALTHY so the history shows the outage.
                await lifecycle.transition(db, dep, S.UNHEALTHY, actor=actor, message=message)
                status = S.UNHEALTHY
            if status == S.SCHEDULED:
                # Same state, new node: record the move explicitly.
                for key, value in fields.items():
                    setattr(dep, key, value)
                dep.updated_at = utcnow()
                await lifecycle.record_event(db, dep, actor=actor, message=note)
            else:
                await lifecycle.transition(db, dep, S.SCHEDULED, actor=actor, message=note, **fields)
            await enqueue_command(db, node.id, dep.id, CommandType.DEPLOY, deploy_payload(dep, req, source))
            audit_service.record(
                db,
                actor_id=None,
                action="deployment.moved",
                resource_type="deployment",
                resource_id=dep.id,
                details={"from_node": str(old_node) if old_node else None, "to_node": str(node.id), "reason": code},
            )
            logger.info("Deployment %s moved from node %s to %s (%s)", dep.id, old_node, node.id, code)
            return True

    await lifecycle.transition(db, dep, S.FAILED, actor=actor, message=message, error_code=code)
    if old_node and cleanup_old_node:
        dep.cleanup_status = "pending"
        await _stop_on_old_node(db, dep, old_node)
    return False


async def restart(db: AsyncSession, dep: Deployment) -> None:
    """Restart a serving deployment on its current node from the cached model. Does not commit."""
    status = S(dep.status)
    if status not in (S.READY, S.UNHEALTHY):
        raise HTTPException(
            status_code=409, detail=f"Only READY or UNHEALTHY deployments can be restarted, not {status.value}"
        )
    node = await db.get(Node, dep.node_id) if dep.node_id else None
    if node is None or node.status != NodeStatus.ONLINE or not node_is_fresh(node):
        raise HTTPException(
            status_code=409,
            detail="The node is offline. The deployment will move to another node automatically if it stays unhealthy.",
        )
    req = await requirements_for(db, dep)
    source = worker_source(await artifact_for(db, dep))
    await lifecycle.transition(
        db, dep, S.PROVISIONING, actor="customer", message="Restart requested", restart_count=dep.restart_count + 1
    )
    await enqueue_command(db, node.id, dep.id, CommandType.RESTART, deploy_payload(dep, req, source))
