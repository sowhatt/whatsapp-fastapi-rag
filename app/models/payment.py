from datetime import datetime
from sqlalchemy import Integer, ForeignKey, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(30), default="cash")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)