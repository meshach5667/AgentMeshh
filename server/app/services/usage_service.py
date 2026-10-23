from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.models.usage import UsageRecord


async def record_usage(db: AsyncSession, deployment_id: str, node_id: str, gpu_seconds: float, cpu_seconds: float):
    usage = UsageRecord(
        deployment_id=deployment_id,
        node_id=node_id,
        gpu_seconds=gpu_seconds,
        cpu_seconds=cpu_seconds,
        period_start=utcnow(),
        period_end=utcnow(),
    )
    db.add(usage)
    await db.commit()
    await db.refresh(usage)
    return usage
