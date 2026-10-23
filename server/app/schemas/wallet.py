import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    balance: Decimal
    currency: str
    model_config = {"from_attributes": True}


class DepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Amount to deposit")


class DepositResponse(BaseModel):
    wallet: WalletResponse
    transaction_id: uuid.UUID
    message: str
