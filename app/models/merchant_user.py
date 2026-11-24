from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MerchantUser(Base):
    """Personne rattachée à un commerçant avec un rôle métier."""

    __tablename__ = "merchant_users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="SELLER", server_default="SELLER", index=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
