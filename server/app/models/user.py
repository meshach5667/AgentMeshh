from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow

if TYPE_CHECKING:
    from app.models.node import Node


class UserRole(str, enum.Enum):  # noqa: UP042
    provider = "provider"
    customer = "customer"
    operator = "operator"
    admin = "admin"


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    provider_profile: Mapped[Provider | None] = relationship(back_populates="user", uselist=False)
    customer_profile: Mapped[Customer | None] = relationship(back_populates="user", uselist=False)


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    payout_status: Mapped[str | None] = mapped_column(String(50), default="pending")
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="provider_profile")
    nodes: Mapped[list[Node]] = relationship(back_populates="owner")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="customer_profile")
