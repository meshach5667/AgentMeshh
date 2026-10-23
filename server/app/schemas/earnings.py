from decimal import Decimal

from pydantic import BaseModel


class EarningsSummary(BaseModel):
    total_earnings: Decimal
    pending_earnings: Decimal
    available_balance: Decimal
    total_deployments: int
    active_deployments: int


class EarningsHistoryItem(BaseModel):
    date: str
    earnings: Decimal
    deployment_count: int


class EarningsHistoryResponse(BaseModel):
    history: list[EarningsHistoryItem]
    total: Decimal
