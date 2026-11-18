"""Durable purchase receipts. shop_scope=0 denotes the legacy merchant scope."""
from datetime import datetime
from sqlalchemy import ForeignKey, String, Integer, DateTime, JSON, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class PurchaseRequest(Base):
    __tablename__ = 'purchase_requests'
    __table_args__ = (
        UniqueConstraint('merchant_id', 'shop_scope', 'operation', 'request_key', name='uq_purchase_request_scope_key'),
        CheckConstraint('shop_scope >= 0', name='ck_purchase_request_scope'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey('merchants.id'))
    shop_scope: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(30))
    request_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
