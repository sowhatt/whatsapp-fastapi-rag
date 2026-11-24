from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserPhone(Base):
    """Identité téléphonique/WhatsApp d'un membre du personnel."""

    __tablename__ = "user_phones"
    __table_args__ = (
        UniqueConstraint("phone_number", name="uq_user_phones_phone_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_users.id"), nullable=False, index=True
    )
    shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("shops.id"), nullable=True, index=True
    )
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
