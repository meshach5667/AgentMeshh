from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles
from app.models.user import UserRole
from app.schemas.node import EnrollmentTokenCreate, EnrollmentTokenOut, NodeCreate, NodeOut, NodeUpdate
from app.services import node_service, worker_service

router = APIRouter()


@router.post("/register")
async def register_node(
    node: NodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(UserRole.provider)),
):
    return await node_service.register_node(db, node, current_user.id)


@router.post("/enrollment-tokens", response_model=EnrollmentTokenOut, status_code=201)
async def create_enrollment_token(
    req: EnrollmentTokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(UserRole.provider)),
):
    """Issue a single-use token (valid for ENROLLMENT_TOKEN_TTL_MINUTES) for enrolling a worker."""
    return await worker_service.create_enrollment_token(db, current_user.id, req.name, req.region)


@router.get("", response_model=list[NodeOut])
async def list_nodes(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    return await node_service.list_nodes(db, current_user.id)


@router.get("/{id}", response_model=NodeOut)
async def get_node(id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    return await node_service.get_node_for_user(db, id, current_user)


@router.patch("/{id}", response_model=NodeOut)
async def update_node(
    id: str, req: NodeUpdate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)
):
    if req.accepting_workloads is None and req.accepts_community_models is None:
        raise HTTPException(status_code=422, detail="Nothing to update")
    node = None
    if req.accepting_workloads is not None:
        node = await node_service.set_accepting_workloads(db, id, current_user, req.accepting_workloads)
    if req.accepts_community_models is not None:
        node = await node_service.set_accepts_community_models(db, id, current_user, req.accepts_community_models)
    return node


@router.post("/{id}/revoke", response_model=NodeOut)
async def revoke_node(id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    return await node_service.revoke_node(db, id, current_user)


@router.post("/{id}/heartbeat", deprecated=True)
async def heartbeat(id: str, authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Node credentials required")
    node = await node_service.authenticate_node(db, id, authorization.removeprefix("Bearer "))
    return await node_service.process_heartbeat(db, node)
