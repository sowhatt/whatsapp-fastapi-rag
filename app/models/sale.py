from datetime import datetime
from sqlalchemy import Integer, ForeignKey, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    paid_amount: Mapped[int] = mapped_column(Integer, default=0)
    remaining_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="credit")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)