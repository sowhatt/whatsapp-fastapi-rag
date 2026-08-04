from datetime import datetime
from sqlalchemy import Integer, DateTime, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    movement_type: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer)
    reference_type: Mapped[str] = mapped_column(String(50))
    reference_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)