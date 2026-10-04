from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _default_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=7)


class OnlineCart(Base):
    __tablename__ = "online_carts"
    __table_args__ = (
        Index("ix_online_carts_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("online_stores.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_default_expiry)


class OnlineCartItem(Base):
    __tablename__ = "online_cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_online_cart_item_cart_product"),
        Index("ix_online_cart_items_cart_id", "cart_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("online_carts.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
