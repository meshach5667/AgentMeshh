"""Control-plane side of worker protocol v1: enrollment, authentication, heartbeats, the command queue,
and deployment status reports."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db_utils import rowcount as _rowcount
from app.core.ids import parse_uuid
from app.core.security import generate_secret, hash_secret, verify_node_api_key
from app.core.timeutil import utcnow
from app.models.deployment import Deployment
from app.models.deployment import DeploymentStatus as S
from app.models.model import ModelArtifact
from app.models.node import Node, NodeHardware, NodeStatus
from app.models.user import Provider
from app.models.worker import CommandStatus, NodeCommand, NodeEnrollmentToken
from app.schemas.worker import (
    Allocation,
    CommandOut,
    DeploymentStatusReport,
    EnrollRequest,
    HardwareReport,
    HeartbeatRequest,
    HeartbeatResponse,
)
from app.services import audit_service, placement_service, release_service
from app.services import deployment_lifecycle as lifecycle
from app.services.commands import cancel_undelivered, enqueue_command  # noqa: F401  (re-exported)
from app.services.scheduler_service import release_reservation

ENROLL_TOKEN_PREFIX = "am_enroll_"
NODE_CREDENTIAL_PREFIX = "am_node_"


# --- Enrollment -----------------------------------------------------------------------------------------


async def create_enrollment_token(db: AsyncSession, user_id, name: str | None, region: str | None) -> dict:
    provider = (await db.execute(select(Provider).where(Provider.user_id == user_id))).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=403, detail="Provider account required")
    token = generate_secret(ENROLL_TOKEN_PREFIX)
    expires_at = utcnow() + timedelta(minutes=settings.ENROLLMENT_TOKEN_TTL_MINUTES)
    row = NodeEnrollmentToken(
        provider_id=provider.id, token_hash=hash_secret(token), name=name, region=region, expires_at=expires_at
    )
    db.add(row)
    await db.flush()
    audit_service.record(
        db,
        actor_id=user_id,
        action="node.enrollment_token_created",
        resource_type="enrollment_token",
        resource_id=row.id,
        details={"name": name, "region": region},
    )
    await db.commit()
    return {"token": token, "expires_at": expires_at}


def _clamp_allocation(alloc: Allocation, hw: HardwareReport) -> Allocation:
    """A worker cannot allocate more than the hardware it reports. (Reported hardware itself is unverified.)"""
    total_vram = sum(g.vram_mb for g in hw.gpus)
    return Allocation(
        cpu_cores=min(alloc.cpu_cores, hw.cpu_cores),
        ram_mb=min(alloc.ram_mb, hw.ram_mb),
        disk_mb=min(alloc.disk_mb, hw.disk_free_mb),
        vram_mb=min(alloc.vram_mb, total_vram),
    )


def _apply_capabilities(node: Node, hw: HardwareReport | None, alloc: Allocation | None, runtimes) -> None:
    if hw is not None and alloc is not None:
        alloc = _clamp_allocation(alloc, hw)
    if alloc is not None:
        node.allocated_cpu_cores = alloc.cpu_cores
        node.allocated_ram_mb = alloc.ram_mb
        node.allocated_disk_mb = alloc.disk_mb
        node.allocated_vram_mb = alloc.vram_mb
    if runtimes is not None:
        node.runtimes = [r.model_dump() for r in runtimes]


async def enroll(db: AsyncSession, req: EnrollRequest) -> dict:
    if req.protocol_version not in settings.WORKER_PROTOCOL_VERSIONS:
        raise HTTPException(status_code=426, detail="Unsupported worker protocol version")

    now = utcnow()
    token_hash = hash_secret(req.token)
    # Claim the token atomically so it can be used exactly once.
    claimed = await db.execute(
        update(NodeEnrollmentToken)
        .where(
            NodeEnrollmentToken.token_hash == token_hash,
            NodeEnrollmentToken.used_at.is_(None),
            NodeEnrollmentToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if _rowcount(claimed) != 1:
        await db.rollback()
        raise HTTPException(status_code=401, detail="Enrollment token is invalid, expired, or already used")
    token = (
        await db.execute(select(NodeEnrollmentToken).where(NodeEnrollmentToken.token_hash == token_hash))
    ).scalar_one()

    credential = generate_secret(NODE_CREDENTIAL_PREFIX)
    hw = req.hardware
    node = Node(
        owner_id=token.provider_id,
        name=token.name or req.name,
        region=token.region,
        public_key=req.public_key,
        api_key_hash=hash_secret(credential),
        status=NodeStatus.ONLINE,
        last_heartbeat=now,
        mode=req.mode,
        worker_version=req.worker_version,
        protocol_version=req.protocol_version,
        accepting_workloads=True,
    )
    _apply_capabilities(node, hw, req.allocation, req.runtimes)
    db.add(node)
    await db.flush()
    gpu = hw.gpus[0] if hw.gpus else None
    db.add(
        NodeHardware(
            node_id=node.id,
            cpu_model=hw.cpu_model,
            cpu_cores=hw.cpu_cores,
            ram_gb=hw.ram_mb // 1024,
            storage_gb=hw.disk_free_mb // 1024,
            gpu_model=gpu.model if gpu else None,
            gpu_count=len(hw.gpus),
            gpu_vram_gb=(gpu.vram_mb // 1024) if gpu else None,
            os_info=f"{hw.os} {hw.arch}",
            capabilities={"gpus": [g.model_dump() for g in hw.gpus], "arch": hw.arch},
        )
    )
    token.node_id = node.id
    audit_service.record(
        db,
        actor_id=None,
        action="node.enrolled",
        resource_type="node",
        resource_id=node.id,
        details={"provider_id": str(token.provider_id), "mode": req.mode, "worker_version": req.worker_version},
    )
    await db.commit()
    return {
        "node_id": node.id,
        "node_credential": credential,
        "protocol_version": req.protocol_version,
        "heartbeat_interval_seconds": settings.WORKER_HEARTBEAT_INTERVAL_SECONDS,
    }


async def authenticate_worker(
    db: AsyncSession, node_id: str | None, credential: str | None, protocol: str | None
) -> Node:
    if protocol is not None:
        try:
            version = int(protocol)
        except ValueError:
            version = -1
        if version not in settings.WORKER_PROTOCOL_VERSIONS:
            raise HTTPException(status_code=426, detail="Unsupported worker protocol version")
    if not node_id or not credential:
        raise HTTPException(status_code=401, detail="Node credentials required")
    try:
        node = await db.get(Node, parse_uuid(node_id, "Node"))
    except HTTPException:
        node = None
    if node is None or not verify_node_api_key(credential, node.api_key_hash):
        raise HTTPException(status_code=401, detail="Invalid node credentials")
    if node.status == NodeStatus.REVOKED:
        raise HTTPException(status_code=401, detail="Node credential revoked")
    if node.status == NodeStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Node suspended")
    return node


# --- Heartbeat and reconciliation ----------------------------------------------------------------------


async def heartbeat(db: AsyncSession, node: Node, req: HeartbeatRequest) -> HeartbeatResponse:
    now = utcnow()
    node.last_heartbeat = now
    node.status = NodeStatus.ONLINE
    node.worker_version = req.worker_version
    node.last_metrics = {k: float(v) for k, v in list(req.metrics.items())[:32]}
    _apply_capabilities(node, req.hardware, req.allocation, req.runtimes)
    node.worker_available = req.available
    node.worker_unavailable_reason = None if req.available else (req.unavailable_reason or "paused")

    stop: list[uuid.UUID] = []
    reported = {r.deployment_id: r for r in req.deployments}
    if reported:
        rows = (await db.execute(select(Deployment).where(Deployment.id.in_(list(reported))))).scalars().all()
        known = {d.id: d for d in rows}
        for dep_id, report in reported.items():
            dep = known.get(dep_id)
            if dep is None or dep.node_id != node.id or dep.deleted_at is not None:
                stop.append(dep_id)
                continue
            status = S(dep.status)
            if status in lifecycle.TERMINAL or status == S.STOPPING:
                if report.state not in ("stopped", "failed"):
                    stop.append(dep_id)
            elif status == S.READY and report.state == "running" and not report.healthy:
                await lifecycle.transition(db, dep, S.UNHEALTHY, actor="worker", message="Health check failing")
            elif status == S.UNHEALTHY and report.state == "running" and report.healthy:
                await lifecycle.transition(db, dep, S.READY, actor="worker", message="Recovered", last_health_at=now)
            elif status in (S.READY, S.UNHEALTHY) and report.healthy:
                dep.last_health_at = now

    # Deployments the control plane believes are serving on this node but the worker no longer reports.
    missing = (
        (
            await db.execute(
                select(Deployment).where(
                    Deployment.node_id == node.id,
                    Deployment.status == S.READY.value,
                    Deployment.id.not_in(list(reported) or [uuid.UUID(int=0)]),
                )
            )
        )
        .scalars()
        .all()
    )
    for dep in missing:
        await lifecycle.transition(
            db, dep, S.UNHEALTHY, actor="system", message="Worker no longer reports this workload"
        )

    await db.commit()
    return HeartbeatResponse(
        server_time=now.timestamp(),
        accepting_workloads=bool(node.accepting_workloads),
        heartbeat_interval_seconds=settings.WORKER_HEARTBEAT_INTERVAL_SECONDS,
        stop_deployments=stop,
        latest_worker_version=release_service.latest_version(),
    )


async def disconnect(db: AsyncSession, node: Node) -> None:
    """Graceful worker shutdown: stop scheduling onto the node right away instead of waiting for the
    heartbeat timeout, and handle its deployments like any other node loss."""
    from app.background.monitors import handle_node_loss

    node.status = NodeStatus.OFFLINE
    await handle_node_loss(db, node, "Worker shut down")
    await db.commit()


# --- Command queue -------------------------------------------------------------------------------------


async def _lease_once(db: AsyncSession, node: Node, max_commands: int) -> list[CommandOut]:
    now = utcnow()
    candidates = (
        (
            await db.execute(
                select(NodeCommand)
                .where(
                    NodeCommand.node_id == node.id,
                    or_(
                        NodeCommand.status == CommandStatus.PENDING.value,
                        (NodeCommand.status == CommandStatus.LEASED.value) & (NodeCommand.lease_expires_at < now),
                    ),
                    NodeCommand.attempts < NodeCommand.max_attempts,
                )
                .order_by(NodeCommand.created_at)
                .limit(max_commands)
            )
        )
        .scalars()
        .all()
    )
    leased: list[CommandOut] = []
    for cmd in candidates:
        result = await db.execute(
            update(NodeCommand)
            .where(NodeCommand.id == cmd.id, NodeCommand.status == cmd.status, NodeCommand.attempts == cmd.attempts)
            .values(
                status=CommandStatus.LEASED.value,
                attempts=cmd.attempts + 1,
                lease_expires_at=now + timedelta(seconds=settings.COMMAND_LEASE_SECONDS),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if _rowcount(result) == 1:
            leased.append(
                CommandOut(
                    id=cmd.id,
                    type=cmd.type,
                    deployment_id=cmd.deployment_id,
                    payload=cmd.payload,
                    attempt=cmd.attempts + 1,
                )
            )
    await db.commit()
    return leased


async def poll_commands(db: AsyncSession, node: Node, max_commands: int, wait_seconds: int) -> list[CommandOut]:
    """Long-poll: return as soon as commands exist, or after ``wait_seconds`` with an empty list."""
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        leased = await _lease_once(db, node, max_commands)
        if leased or asyncio.get_running_loop().time() >= deadline:
            return leased
        await asyncio.sleep(1.0)


async def ack_command(db: AsyncSession, node: Node, command_id: str, status: str, error: str | None) -> None:
    cmd = await db.get(NodeCommand, parse_uuid(command_id, "Command"))
    if cmd is None or cmd.node_id != node.id:
        raise HTTPException(status_code=404, detail="Command not found")
    if cmd.status in (CommandStatus.SUCCEEDED.value, CommandStatus.FAILED.value, CommandStatus.CANCELLED.value):
        return  # duplicate ack: idempotent
    now = utcnow()
    cmd.status = CommandStatus.FAILED.value if status == "failed" else CommandStatus.SUCCEEDED.value
    cmd.error = error
    cmd.completed_at = now
    if status == "failed" and cmd.deployment_id:
        dep = await db.get(Deployment, cmd.deployment_id)
        if dep and S(dep.status) not in lifecycle.TERMINAL and dep.node_id == node.id:
            await placement_service.fail_or_reschedule(
                db,
                dep,
                code="WORKER_REJECTED",
                message=error or f"{cmd.type} command failed",
                actor="worker",
                cleanup_old_node=False,
            )
    await db.commit()


def deployment_endpoint(dep: Deployment) -> str:
    """Runtime-native base URL: Ollama deployments also expose Ollama's own API under /ollama; every runtime
    exposes the OpenAI-compatible API under /v1."""
    base = f"{settings.PUBLIC_BASE_URL}{settings.API_V1_PREFIX}/deployments/{dep.id}"
    return f"{base}/ollama" if dep.runtime == "ollama" else f"{base}/v1"


# --- Deployment status reports -------------------------------------------------------------------------


async def report_deployment_status(
    db: AsyncSession, node: Node, deployment_id: str, report: DeploymentStatusReport
) -> dict:
    dep = await db.get(Deployment, parse_uuid(deployment_id, "Deployment"))
    if dep is None or dep.node_id != node.id:
        raise HTTPException(status_code=404, detail="Deployment not found")

    current = S(dep.status)
    now = utcnow()
    state = report.state

    if state == "STOPPED":
        # Cleanup confirmed by the worker. Valid from STOPPING, and also after the control plane has
        # already given up on the deployment (late cleanup confirmation).
        if current == S.STOPPING:
            final = S.STOPPED if dep.was_ready else S.CANCELLED
            await lifecycle.transition(db, dep, final, actor="worker", message=report.message or "Workload stopped")
            dep.cleanup_status = "done"
            await release_reservation(db, dep.id)
        elif current in lifecycle.TERMINAL:
            dep.cleanup_status = "done"  # late confirmation; the reservation was already released
        else:
            moved = await placement_service.fail_or_reschedule(
                db,
                dep,
                code=report.error_code or "WORKLOAD_EXITED",
                message=report.message or "Workload stopped unexpectedly",
                actor="worker",
                cleanup_old_node=False,
            )
            if not moved:
                dep.cleanup_status = "done"
        await db.commit()
        return {"status": dep.status}

    if current in lifecycle.TERMINAL or current == S.STOPPING:
        # Late progress for a deployment that is being or has been stopped: ignore, the worker will be told
        # to stop via the STOP command or heartbeat reconciliation.
        return {"status": dep.status, "ignored": True}

    if state == "FAILED":
        # The worker removes its runtime before reporting FAILED, so there is nothing to clean up there.
        moved = await placement_service.fail_or_reschedule(
            db,
            dep,
            code=report.error_code or "PROVISIONING_FAILED",
            message=report.message or "Provisioning failed",
            actor="worker",
            cleanup_old_node=False,
        )
        if not moved:
            dep.cleanup_status = "done"
        await db.commit()
        return {"status": dep.status}

    target = S(state)
    if current in (S.READY, S.UNHEALTHY) and target in (S.PROVISIONING, S.STARTING):
        # Only a customer restart may take a serving deployment back to provisioning; a worker report
        # like this is stale (e.g. sent while re-adopting after its own restart).
        raise HTTPException(status_code=409, detail=f"{current.value} -> {target.value} is not allowed from a worker")
    if target == current:
        if report.message:
            await lifecycle.record_event(db, dep, actor="worker", message=report.message)
        dep.updated_at = now  # progress resets the stall timeout
        await db.commit()
        return {"status": dep.status}

    extra: dict[str, Any] = {}
    if target == S.READY:
        extra = {
            "model_digest": report.model_digest,
            "last_health_at": now,
            "endpoint": deployment_endpoint(dep),
            "started_at": dep.started_at or now,
        }
    if target == S.READY and dep.artifact_id:
        # Evidence that this model/runtime combination really serves, not just that it is in the catalog.
        artifact = await db.get(ModelArtifact, dep.artifact_id)
        if artifact is not None:
            artifact.last_ready_at = now
    try:
        ok = await lifecycle.transition(db, dep, target, actor="worker", message=report.message, **extra)
    except lifecycle.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if not ok:
        raise HTTPException(status_code=409, detail="Deployment status changed concurrently")
    await db.commit()
    return {"status": dep.status}
