"""Payment idempotency journal, committed with all financial rows."""
from datetime import datetime
from sqlalchemy import ForeignKey, String, Integer, DateTime, JSON, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class PaymentRequest(Base):
    __tablename__ = 'payment_requests'
    __table_args__ = (
        UniqueConstraint('merchant_id', 'shop_scope', 'request_key', name='uq_payment_request_scope_key'),
        CheckConstraint('shop_scope >= 0', name='ck_payment_request_scope'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey('merchants.id'))
    shop_scope: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey('payments.id'), nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
