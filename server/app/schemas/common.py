from typing import Any

from pydantic import BaseModel


class PaginatedResponse(BaseModel):
    total: int
    items: list[Any]
    page: int
    size: int
