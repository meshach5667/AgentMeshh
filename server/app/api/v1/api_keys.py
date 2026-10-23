import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_roles
from app.models.user import UserRole
from app.services import api_key_service

router = APIRouter()


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["inference"], max_length=10)
    deployment_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    deployment_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="The secret. Shown once; store it securely.")


customer_only = require_roles(UserRole.customer)


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_key(req: ApiKeyCreate, db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    key, secret = await api_key_service.create_api_key(
        db, user, req.name, req.scopes, str(req.deployment_id) if req.deployment_id else None, req.expires_at
    )
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=secret)


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    return await api_key_service.list_api_keys(db, user)


@router.delete("/{key_id}", response_model=ApiKeyOut)
async def revoke_key(key_id: str, db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    return await api_key_service.revoke_api_key(db, user, key_id)
