import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.dependencies import is_staff
from app.core.ids import parse_uuid
from app.core.security import get_password_hash, verify_node_api_key
from app.core.timeutil import utcnow
from app.models.node import Node, NodeHardware, NodeStatus
from app.models.user import Provider, User
from app.schemas.node import NodeCreate
from app.services import audit_service


async def register_node(db: AsyncSession, node_data: NodeCreate, user_id: uuid.UUID):
    result = await db.execute(select(Provider).filter(Provider.user_id == user_id))
    provider = result.scalars().first()
    if not provider:
        raise HTTPException(status_code=403, detail="Provider account required")

    api_key = f"am_node_{uuid.uuid4().hex}"
    node = Node(
        owner_id=provider.id,
        name=node_data.name,
        public_key=node_data.public_key,
        region=node_data.region,
        api_key_hash=get_password_hash(api_key),
    )
    db.add(node)
    await db.flush()
    if node_data.hardware:
        db.add(NodeHardware(node_id=node.id, **node_data.hardware.model_dump()))
    await db.commit()
    await db.refresh(node)
    # The plaintext key is returned exactly once; only its hash is stored.
    return {"id": node.id, "node_id": node.id, "api_key": api_key, "status": node.status}


async def list_nodes(db: AsyncSession, user_id: uuid.UUID):
    result = await db.execute(select(Provider).filter(Provider.user_id == user_id))
    provider = result.scalars().first()
    if not provider:
        return []
    result = await db.execute(select(Node).filter(Node.owner_id == provider.id))
    return result.scalars().all()


async def get_node(db: AsyncSession, node_id: str | uuid.UUID) -> Node:
    result = await db.execute(select(Node).filter(Node.id == parse_uuid(node_id, "Node")))
    node = result.scalars().first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


async def get_node_for_user(db: AsyncSession, node_id: str, user: User) -> Node:
    """Return a node only if the caller owns it or is platform staff. Other callers get 404, not 403,
    so node IDs cannot be probed."""
    node = await get_node(db, node_id)
    if is_staff(user):
        return node
    result = await db.execute(select(Provider).filter(Provider.user_id == user.id))
    provider = result.scalars().first()
    if not provider or node.owner_id != provider.id:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


async def process_heartbeat(db: AsyncSession, node: Node):
    if node.status == NodeStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Node suspended")
    node.last_heartbeat = utcnow()
    node.status = NodeStatus.ONLINE
    await db.commit()
    return {"status": "ok"}


async def authenticate_node(db: AsyncSession, node_id: str, api_key: str) -> Node:
    try:
        node = await get_node(db, node_id)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid node credentials") from None
    if not verify_node_api_key(api_key, node.api_key_hash):
        raise HTTPException(status_code=401, detail="Invalid node credentials")
    return node


async def set_accepting_workloads(db: AsyncSession, node_id: str, user: User, accepting: bool) -> Node:
    """Pause or resume scheduling onto a node. Existing deployments keep running (drain)."""
    node = await get_node_for_user(db, node_id, user)
    node.accepting_workloads = accepting
    audit_service.record(
        db,
        actor_id=user.id,
        action="node.resumed" if accepting else "node.paused",
        resource_type="node",
        resource_id=node.id,
    )
    await db.commit()
    await db.refresh(node)
    return node


async def set_accepts_community_models(db: AsyncSession, node_id: str, user: User, accept: bool) -> Node:
    """Provider opt-in to unreviewed community models. Opting out stops new placements; deployments already
    running keep running until they stop or move. Only the provider can consent; staff may only opt a node out."""
    node = await get_node_for_user(db, node_id, user)
    if accept and is_staff(user):
        raise HTTPException(status_code=403, detail="Only the node's provider can opt in to community models")
    node.accepts_community_models = accept
    audit_service.record(
        db,
        actor_id=user.id,
        action="node.community_models_accepted" if accept else "node.community_models_refused",
        resource_type="node",
        resource_id=node.id,
    )
    await db.commit()
    await db.refresh(node)
    return node


async def revoke_node(db: AsyncSession, node_id: str, user: User) -> Node:
    """Revoke a node's credential (disconnect or compromise). Its active deployments fail immediately and
    their reservations are released; the worker can no longer authenticate."""
    from app.models.deployment import Deployment
    from app.services import deployment_lifecycle as lifecycle
    from app.services import placement_service
    from app.services.scheduler_service import release_reservation
    from app.services.tunnel import broker

    node = await get_node_for_user(db, node_id, user)
    audit_service.record(
        db,
        actor_id=user.id,
        action="node.revoked",
        resource_type="node",
        resource_id=node.id,
        details={"by_role": user.role},
    )
    node.api_key_hash = None
    node.status = NodeStatus.REVOKED
    node.accepting_workloads = False
    active = (
        (
            await db.execute(
                select(Deployment).where(
                    Deployment.node_id == node.id, Deployment.status.in_([s.value for s in lifecycle.ACTIVE])
                )
            )
        )
        .scalars()
        .all()
    )
    actor = "operator" if is_staff(user) else "provider"
    for dep in active:
        if lifecycle.S(dep.status) == lifecycle.S.STOPPING:
            # Was already being stopped; the node can no longer confirm, so finish it here.
            final = lifecycle.S.STOPPED if dep.was_ready else lifecycle.S.CANCELLED
            await lifecycle.transition(db, dep, final, actor=actor, message="Node credential revoked")
            dep.cleanup_status = "pending_node"
            await release_reservation(db, dep.id)
            continue
        # A revoked worker stops all of its workloads itself, so no cleanup command is queued.
        await placement_service.fail_or_reschedule(
            db, dep, code="NODE_REVOKED", message="Node credential revoked", actor=actor, cleanup_old_node=False
        )
    await db.commit()
    await broker.close_node(node.id)
    await db.refresh(node)
    return node
