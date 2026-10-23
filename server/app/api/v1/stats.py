"""Public, unauthenticated network figures for the landing page. Counts only."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import reporting_service

router = APIRouter()


@router.get("/public")
async def public_stats(db: AsyncSession = Depends(get_db)):
    """Live counts from the database (no node names, owners, locations, or hardware), plus which product
    features are actually enabled on this deployment of AgentMesh."""
    return await reporting_service.public_stats(db)
