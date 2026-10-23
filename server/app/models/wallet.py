import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.core.timeutil import utcnow


class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=0)
    currency: Mapped[str | None] = mapped_column(String(10), default=lambda: settings.BILLING_CURRENCY)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
