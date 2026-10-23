"""Worker protocol v1 endpoints. Used identically by the Docker worker and the installable agent.

All calls are outbound from the worker. Authentication: ``Authorization: Bearer <node credential>`` plus
``X-AgentMesh-Node-Id`` and ``X-AgentMesh-Protocol`` headers (enrollment uses a one-time token instead).
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, session_scope
from app.models.node import Node
from app.schemas.worker import (
    CommandAck,
    DeploymentStatusReport,
    EnrollRequest,
    EnrollResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    PollRequest,
    PollResponse,
)
from app.services import release_service, worker_service
from app.services.tunnel import WorkerConnection, broker

logger = logging.getLogger(__name__)
router = APIRouter()


async def current_node(
    db: AsyncSession = Depends(get_db),
    authorization: str = Header(default=""),
    x_agentmesh_node_id: str | None = Header(default=None),
    x_agentmesh_protocol: str | None = Header(default=None),
) -> Node:
    credential = authorization[7:] if authorization.lower().startswith("bearer ") else None
    return await worker_service.authenticate_worker(db, x_agentmesh_node_id, credential, x_agentmesh_protocol or "1")


@router.post("/enroll", response_model=EnrollResponse)
async def enroll(req: EnrollRequest, db: AsyncSession = Depends(get_db)):
    return await worker_service.enroll(db, req)


@router.get("/releases/latest")
async def latest_release(node: Node = Depends(current_node)):
    release = release_service.latest()
    if release is None:
        raise HTTPException(status_code=404, detail="No worker release published")
    return release


@router.get("/releases/files/{name}")
async def release_file(name: str, node: Node = Depends(current_node)):
    path = release_service.wheel_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Release file not found")
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.get("/whoami")
async def whoami(node: Node = Depends(current_node)):
    """Read-only credential check used by `agentmesh-worker doctor`."""
    return {
        "node_id": str(node.id),
        "name": node.name,
        "status": node.status,
        "accepting_workloads": node.accepting_workloads,
        "worker_available": node.worker_available,
    }


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(req: HeartbeatRequest, node: Node = Depends(current_node), db: AsyncSession = Depends(get_db)):
    return await worker_service.heartbeat(db, node, req)


@router.post("/disconnect")
async def disconnect(node: Node = Depends(current_node), db: AsyncSession = Depends(get_db)):
    await worker_service.disconnect(db, node)
    return {"ok": True}


@router.post("/commands/poll", response_model=PollResponse)
async def poll(req: PollRequest, node: Node = Depends(current_node), db: AsyncSession = Depends(get_db)):
    return {"commands": await worker_service.poll_commands(db, node, req.max_commands, req.wait_seconds)}


@router.post("/commands/{command_id}/ack")
async def ack(command_id: str, req: CommandAck, node: Node = Depends(current_node), db: AsyncSession = Depends(get_db)):
    await worker_service.ack_command(db, node, command_id, req.status, req.error)
    return {"ok": True}


@router.post("/deployments/{deployment_id}/status")
async def deployment_status(
    deployment_id: str,
    report: DeploymentStatusReport,
    node: Node = Depends(current_node),
    db: AsyncSession = Depends(get_db),
):
    return await worker_service.report_deployment_status(db, node, deployment_id, report)


@router.websocket("/tunnel")
async def tunnel(websocket: WebSocket):
    headers = websocket.headers
    auth = headers.get("authorization", "")
    credential = auth[7:] if auth.lower().startswith("bearer ") else None
    try:
        async with session_scope() as db:
            node = await worker_service.authenticate_worker(
                db, headers.get("x-agentmesh-node-id"), credential, headers.get("x-agentmesh-protocol") or "1"
            )
            node_id = node.id
    except Exception:  # noqa: BLE001
        await websocket.close(code=4401)
        return
    await websocket.accept()
    conn = WorkerConnection(node_id=node_id, send_json=websocket.send_json, close=websocket.close)
    await broker.register(conn)
    logger.info("Worker tunnel connected for node %s", node_id)
    try:
        await broker.handle_messages(conn, websocket.receive_text)
    except WebSocketDisconnect:
        pass
    finally:
        broker.unregister(conn)
        logger.info("Worker tunnel closed for node %s", node_id)
