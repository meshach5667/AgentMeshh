from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.node import Node, NodeStatus
from app.schemas.marketplace import MarketplaceNodeResponse

router = APIRouter()


@router.get("/nodes", response_model=list[MarketplaceNodeResponse])
async def search_nodes(
    db: AsyncSession = Depends(get_db),
    min_vram_gb: int | None = Query(None),
    region: str | None = Query(None),
    gpu_model: str | None = Query(None),
):
    query = (
        select(Node)
        .options(selectinload(Node.hardware), selectinload(Node.pricing))
        .filter(Node.status.in_([NodeStatus.AVAILABLE, NodeStatus.ONLINE]))
    )
    if region:
        query = query.filter(Node.region == region)

    result = await db.execute(query)
    nodes = result.scalars().all()

    response = []
    for node in nodes:
        hw = node.hardware
        pr = node.pricing
        if min_vram_gb and (not hw or not hw.gpu_vram_gb or hw.gpu_vram_gb < min_vram_gb):
            continue
        if gpu_model and (not hw or not hw.gpu_model or gpu_model.lower() not in hw.gpu_model.lower()):
            continue
        response.append(
            MarketplaceNodeResponse(
                node_id=node.id,
                name=node.name,
                region=node.region,
                gpu_model=hw.gpu_model if hw else None,
                gpu_count=(hw.gpu_count or 0) if hw else 0,
                gpu_vram_gb=hw.gpu_vram_gb if hw else None,
                cpu_model=hw.cpu_model if hw else None,
                cpu_cores=hw.cpu_cores if hw else None,
                ram_gb=hw.ram_gb if hw else None,
                gpu_hour_price=pr.gpu_hour_price if pr else None,
                reputation_score=node.reputation_score if node.reputation_score is not None else Decimal("100"),
                status=str(node.status),
            )
        )
    return response


@router.get("/pricing")
async def get_pricing():
    from app.services.pricing_service import recommend_price

    recommendations = [
        {"gpu_model": "RTX 4090", "recommended_price": recommend_price("RTX 4090", 24, "us-east")},
        {"gpu_model": "A100", "recommended_price": recommend_price("A100", 80, "us-east")},
        {"gpu_model": "H100", "recommended_price": recommend_price("H100", 80, "us-east")},
    ]
    return {"recommendations": recommendations}
