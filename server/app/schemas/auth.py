import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole

SELF_REGISTRATION_ROLES = (UserRole.customer, UserRole.provider)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    role: UserRole

    @field_validator("role")
    @classmethod
    def _self_service_roles_only(cls, role: UserRole) -> UserRole:
        # Operator/admin accounts must be provisioned by an existing administrator, never self-registered.
        if role not in SELF_REGISTRATION_ROLES:
            raise ValueError("role must be 'customer' or 'provider'")
        return role


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
