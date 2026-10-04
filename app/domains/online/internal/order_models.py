from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _order_reference() -> str:
    return "WO-" + uuid4().hex[:10].upper()


class OnlineOrder(Base):
    __tablename__ = "online_orders"
    __table_args__ = (
        Index("ix_online_orders_merchant_status", "merchant_id", "status"),
        Index("ix_online_orders_store_created_at", "store_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("online_stores.id"), nullable=False, index=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("business_transactions.id"), nullable=False, unique=True, index=True
    )
    cart_id: Mapped[int] = mapped_column(ForeignKey("online_carts.id"), nullable=False, unique=True)

    reference: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, index=True, default=_order_reference
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    delivery_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="pickup")
    delivery_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF")
    subtotal_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unpaid")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class OnlineOrderItem(Base):
    __tablename__ = "online_order_items"
    __table_args__ = (Index("ix_online_order_items_order_id", "order_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("online_orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    unit_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)
