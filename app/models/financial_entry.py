from datetime import datetime
from sqlalchemy import Integer, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class FinancialEntry(Base):
    __tablename__ = "financial_entries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entry_type: Mapped[str] = mapped_column(String(20))  # income, expense, transfer, adjustment
    amount: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(30), default="cash")  # cash, moov_money, mtn_momo, bank
    label: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    origin_kind: Mapped[str] = mapped_column(String(20), default="manual")  # manual, linked
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)