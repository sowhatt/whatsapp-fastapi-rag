from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class PurchasingReceipt(Base):
    """Immutable response committed with its business writes, never expired."""
    __tablename__ = 'purchasing_receipts'
    merchant_id: Mapped[int] = mapped_column(ForeignKey('merchants.id'), primary_key=True)
    key: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey('shops.id'), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('merchant_users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
