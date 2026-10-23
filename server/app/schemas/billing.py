import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

PRICE = Field(ge=0, le=Decimal("1000000"), max_digits=18, decimal_places=8)


class PricingRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_core_hour: Decimal = PRICE
    ram_gb_hour: Decimal = PRICE
    vram_gb_hour: Decimal = PRICE
    input_tokens_per_million: Decimal = PRICE
    output_tokens_per_million: Decimal = PRICE
    platform_fee_rate: Decimal = Field(ge=0, le=Decimal("0.5"), max_digits=5, decimal_places=4)
    effective_from: datetime | None = Field(None, description="UTC; defaults to now. Cannot be in the past")
    notes: str | None = Field(None, max_length=500)


class PricingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    currency: str
    cpu_core_hour: Decimal
    ram_gb_hour: Decimal
    vram_gb_hour: Decimal
    input_tokens_per_million: Decimal
    output_tokens_per_million: Decimal
    platform_fee_rate: Decimal
    effective_from: datetime
    notes: str | None
    created_at: datetime


class PricingOut(BaseModel):
    current: PricingRuleOut | None
    upcoming: list[PricingRuleOut]
    currency: str
    min_prepaid_hours: float
    billing_interval_seconds: int


class ChargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    deployment_id: uuid.UUID
    node_id: uuid.UUID | None
    pricing_rule_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    ready_seconds: float
    cpu_cores: int
    ram_mb: int
    vram_mb: int
    input_tokens: int
    output_tokens: int
    resource_amount: Decimal
    token_amount: Decimal
    amount: Decimal
    provider_amount: Decimal
    platform_fee: Decimal
    currency: str
    created_at: datetime


class TopupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    amount: Decimal
    currency: str
    status: str
    provider_status: str | None
    authorization_url: str | None
    channel: str | None
    failure_reason: str | None
    paid_at: datetime | None
    created_at: datetime


class PayoutAccountSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_number: str = Field(pattern=r"^\d{6,20}$")
    bank_code: str = Field(pattern=r"^[A-Za-z0-9-]{1,20}$")


class PayoutAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bank_code: str
    bank_name: str | None
    account_name: str | None
    account_last4: str
    currency: str
    updated_at: datetime


class PayoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class PayoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal
    currency: str
    reference: str
    status: str
    failure_reason: str | None
    decided_at: datetime | None
    completed_at: datetime | None
    reconciled_at: datetime | None
    created_at: datetime


class PayoutDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(None, max_length=300)
