import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class TransactionTypeEnum(str, Enum):  # noqa: UP042
    DEPOSIT = "DEPOSIT"
    COMPUTE_CHARGE = "COMPUTE_CHARGE"
    PROVIDER_CREDIT = "PROVIDER_CREDIT"
    PLATFORM_FEE = "PLATFORM_FEE"
    REFUND = "REFUND"
    PAYOUT = "PAYOUT"


class TransactionStatusEnum(str, Enum):  # noqa: UP042
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class TransactionResponse(BaseModel):
    id: uuid.UUID
    from_wallet: uuid.UUID | None = None
    to_wallet: uuid.UUID | None = None
    amount: Decimal
    type: TransactionTypeEnum
    status: TransactionStatusEnum
    deployment_id: uuid.UUID | None = None
    reference: str | None = None
    description: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int
