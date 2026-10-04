from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockReservation(Base):
    """Temporary hold on physical stock before a transaction is finalized."""

    __tablename__ = "stock_reservations"
    __table_args__ = (
        Index(
            "ix_stock_reservations_product_status_expires",
            "product_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_stock_reservations_source",
            "source_type",
            "source_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
