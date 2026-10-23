import uuid
from decimal import Decimal

from pydantic import BaseModel


class MarketplaceNodeResponse(BaseModel):
    node_id: uuid.UUID
    name: str | None = None
    region: str | None = None
    gpu_model: str | None = None
    gpu_count: int = 0
    gpu_vram_gb: int | None = None
    cpu_model: str | None = None
    cpu_cores: int | None = None
    ram_gb: int | None = None
    gpu_hour_price: Decimal | None = None
    reputation_score: Decimal = Decimal("100.00")
    status: str
    model_config = {"from_attributes": True}


class MarketplaceSearchParams(BaseModel):
    min_vram_gb: int | None = None
    min_ram_gb: int | None = None
    min_cpu_cores: int | None = None
    gpu_model: str | None = None
    max_gpu_hour_price: Decimal | None = None
    region: str | None = None
    status: str | None = "AVAILABLE"


class PricingRecommendation(BaseModel):
    gpu_model: str
    recommended_gpu_hour_price: Decimal
    market_low: Decimal
    market_high: Decimal
    market_median: Decimal
