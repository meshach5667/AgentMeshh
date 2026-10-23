import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class UsageRecordResponse(BaseModel):
    id: uuid.UUID
    deployment_id: uuid.UUID | None = None
    workload_id: uuid.UUID | None = None
    node_id: uuid.UUID | None = None
    gpu_seconds: float | None = 0
    cpu_seconds: float | None = 0
    storage_usage: float | None = 0
    bandwidth_usage: float | None = 0
    total_cost: Decimal | None = Decimal("0")
    period_start: datetime | None = None
    period_end: datetime | None = None
    created_at: datetime
    kind: str | None = None
    request_id: str | None = None
    endpoint: str | None = None
    status_code: int | None = None
    outcome: str | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    token_source: str | None = None
    response_bytes: int | None = None
    model_config = {"from_attributes": True}


class UsageCreateRequest(BaseModel):
    deployment_id: uuid.UUID
    gpu_seconds: float = 0
    cpu_seconds: float = 0
    storage_usage: float = 0
    bandwidth_usage: float = 0
    period_start: datetime
    period_end: datetime


class UsageSummaryResponse(BaseModel):
    total_gpu_hours: float
    total_cpu_hours: float
    total_cost: Decimal
    record_count: int
