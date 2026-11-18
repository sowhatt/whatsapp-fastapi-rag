"""Shared PostgreSQL attempt budgets, independent of IP and device identifiers."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MerchantAuthAttempt(Base):
    __tablename__ = "merchant_auth_attempts"
    __table_args__ = (CheckConstraint("attempts >= 0", name="ck_auth_attempts_positive"),)

    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("merchant_users.id"), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(20), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
