"""Persisted node command queue: enqueueing and cancelling. Leasing lives in worker_service."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db_utils import rowcount as _rowcount
from app.core.timeutil import utcnow
from app.models.worker import CommandStatus, CommandType, NodeCommand


async def enqueue_command(db: AsyncSession, node_id, deployment_id, type_: CommandType, payload: dict) -> NodeCommand:
    """Queue a command. A STOP is not duplicated while an identical one is outstanding. Does not commit."""
    if type_ == CommandType.STOP:
        existing = (
            await db.execute(
                select(NodeCommand).where(
                    NodeCommand.deployment_id == deployment_id,
                    NodeCommand.type == CommandType.STOP.value,
                    NodeCommand.status.in_([CommandStatus.PENDING.value, CommandStatus.LEASED.value]),
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing
    cmd = NodeCommand(
        node_id=node_id,
        deployment_id=deployment_id,
        type=type_.value,
        payload=payload,
        status=CommandStatus.PENDING.value,
        attempts=0,
        max_attempts=settings.COMMAND_MAX_ATTEMPTS,
    )
    db.add(cmd)
    return cmd


async def cancel_undelivered(db: AsyncSession, deployment_id, type_: CommandType) -> bool:
    """Cancel a command that no worker has leased yet. Returns True if one was cancelled."""
    result = await db.execute(
        update(NodeCommand)
        .where(
            NodeCommand.deployment_id == deployment_id,
            NodeCommand.type == type_.value,
            NodeCommand.status == CommandStatus.PENDING.value,
            NodeCommand.attempts == 0,
        )
        .values(status=CommandStatus.CANCELLED.value, completed_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return _rowcount(result) > 0
