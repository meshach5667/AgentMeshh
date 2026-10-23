"""AI deployment agent API.

Customers:
    POST /ai/deployments               describe a deployment and authorize limits (starts a run)
    GET  /ai/deployments               list runs
    GET  /ai/deployments/{id}          progress, plan, estimated and actual cost, verified endpoint
    POST /ai/deployments/{id}/cancel   stop the run and any deployment it created
    GET  /ai/deployments/{id}/events   run history
    GET  /ai/health                    whether the AI service is available (no infrastructure details)

Internal inference machines (bearer AI_INFERENCE_TOKEN, X-AgentMesh-Inference-Node: <AI_INFERENCE_NODE_ID>):
    POST /ai/inference/heartbeat
    POST /ai/inference/lease
    POST /ai/inference/requests/{id}/result
"""

import asyncio
import hmac
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, is_staff, require_roles
from app.core.ids import parse_uuid
from app.core.ratelimit import limiters
from app.models.ai import AiInferenceNode, AiRun, AiRunEvent
from app.models.user import Customer, User, UserRole
from app.schemas.ai import (
    AiDeploymentCreate,
    AiHealthOut,
    AiRunEventOut,
    AiRunOut,
    InferenceHeartbeat,
    InferenceJob,
    InferenceLeaseRequest,
    InferenceResult,
)
from app.services.ai import inference_queue, workflow

router = APIRouter()

NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


async def _advance_quietly(run_id: uuid.UUID) -> None:
    try:
        await workflow.advance(run_id)
    except Exception:  # noqa: BLE001
        pass  # logged by advance; the background monitor retries


# --- Customers -----------------------------------------------------------------------------------------


@router.post("/deployments", response_model=AiRunOut, status_code=202)
async def create_ai_deployment(
    body: AiDeploymentCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.customer)),
):
    allowed, retry_after = await limiters.requests.allow(f"ai-run:{user.id}", settings.AI_RATE_LIMIT_PER_MINUTE)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many AI deployment requests",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
    run = await workflow.create_run(db, user, body.request, body.limits, body.idempotency_key)
    background.add_task(_advance_quietly, run.id)
    return await workflow.view(db, run)


@router.get("/deployments", response_model=list[AiRunOut])
async def list_ai_deployments(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    customer = (await db.execute(select(Customer).where(Customer.user_id == user.id))).scalar_one_or_none()
    if customer is None:
        return []
    runs = (
        (
            await db.execute(
                select(AiRun).where(AiRun.customer_id == customer.id).order_by(AiRun.created_at.desc()).limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [await workflow.view(db, r) for r in runs]


@router.get("/deployments/{run_id}", response_model=AiRunOut)
async def get_ai_deployment(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await workflow.view(db, await workflow.get_run_for_user(db, run_id, user))


@router.post("/deployments/{run_id}/cancel", response_model=AiRunOut)
async def cancel_ai_deployment(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    run = await workflow.get_run_for_user(db, run_id, user)
    await workflow.request_cancel(db, run, user)
    await workflow.advance(run.id)
    return await workflow.view(db, await workflow.get_run_for_user(db, run_id, user))


@router.get("/deployments/{run_id}/events", response_model=list[AiRunEventOut])
async def ai_deployment_events(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    run = await workflow.get_run_for_user(db, run_id, user)
    rows = (
        (
            await db.execute(
                select(AiRunEvent).where(AiRunEvent.run_id == run.id).order_by(AiRunEvent.created_at, AiRunEvent.id)
            )
        )
        .scalars()
        .all()
    )
    return rows[-500:]


@router.get("/health", response_model=AiHealthOut)
async def ai_health(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    h = await inference_queue.health(db)
    nodes = None
    if is_staff(user):
        nodes = [
            {
                "id": n.id,
                "last_seen": n.last_seen,
                "fresh": inference_queue.node_is_fresh(n),
                "model": n.model,
                "ollama_version": n.ollama_version,
                "ollama_ok": n.ollama_ok,
                "model_ready": n.model_ready,
                "accepting": n.accepting,
                "reason": n.reason,
                "in_flight": n.in_flight,
                "metrics": n.metrics,
            }
            for n in h.nodes
        ]
    return AiHealthOut(
        status=h.status, available=h.available, model=h.model, queue_depth=h.queue_depth, message=h.message, nodes=nodes
    )


# --- Inference machines --------------------------------------------------------------------------------


async def inference_node(
    request: Request,
    db: AsyncSession = Depends(get_db),
    node_id: str | None = Header(None, alias="X-AgentMesh-Inference-Node"),
) -> str:
    """Authenticate an inference machine. Disabled entirely unless AI_INFERENCE_TOKEN is set."""
    expected = settings.AI_INFERENCE_TOKEN
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not expected or not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid inference credentials")
    if not node_id or not NODE_ID_RE.fullmatch(node_id):
        raise HTTPException(status_code=400, detail="X-AgentMesh-Inference-Node must be a simple identifier")
    return node_id


@router.post("/inference/heartbeat")
async def inference_heartbeat(
    body: InferenceHeartbeat, db: AsyncSession = Depends(get_db), node_id: str = Depends(inference_node)
):
    report = body.model_dump()
    metrics = body.metrics.model_dump() if body.metrics else {}
    report["metrics"] = {k: v for k, v in metrics.items() if v is not None}
    node = await inference_queue.heartbeat(db, node_id, report)
    return {
        "accepted": node.accepting,
        "expected_model": settings.OLLAMA_MODEL,
        "reason": node.reason,
        "heartbeat_interval_seconds": max(5, settings.AI_NODE_TIMEOUT_SECONDS // 3),
    }


@router.post("/inference/lease", response_model=list[InferenceJob])
async def inference_lease(
    body: InferenceLeaseRequest, db: AsyncSession = Depends(get_db), node_id: str = Depends(inference_node)
):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + body.wait_seconds
    while True:
        node = await db.get(AiInferenceNode, node_id)
        if node is None:
            raise HTTPException(status_code=409, detail="Send a heartbeat first")
        await db.refresh(node)
        leased = await inference_queue.lease(db, node, body.max_requests)
        if leased or loop.time() >= deadline:
            break
        await asyncio.sleep(1.0)
    return [
        InferenceJob(
            id=r.id,
            model=r.model,
            messages=(r.payload or {}).get("messages", []),
            format=(r.payload or {}).get("format"),
            options=(r.payload or {}).get("options", {}),
            timeout_seconds=settings.AI_REQUEST_TIMEOUT,
        )
        for r in leased
    ]


@router.post("/inference/requests/{request_id}/result")
async def inference_result(
    request_id: str,
    body: InferenceResult,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    node_id: str = Depends(inference_node),
):
    req = await inference_queue.complete(
        db,
        node_id,
        parse_uuid(request_id, "Inference request"),
        content=body.content,
        error_code=body.error_code,
        error=body.error,
        retryable=body.retryable,
        latency_ms=body.latency_ms,
        prompt_tokens=body.prompt_tokens,
        output_tokens=body.output_tokens,
        model=body.model,
    )
    if req is None:
        await db.rollback()
        return {"accepted": False}
    await db.commit()
    if req.run_id is not None and req.status in ("COMPLETED", "FAILED"):
        background.add_task(_advance_quietly, req.run_id)
    return {"accepted": True, "status": req.status}
