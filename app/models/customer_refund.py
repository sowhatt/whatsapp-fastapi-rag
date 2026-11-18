from datetime import datetime, timezone
from sqlalchemy import ForeignKey, DateTime, String, Integer, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

def utcnow(): return datetime.now(timezone.utc)

class SaleCancellation(Base):
    __tablename__='sale_cancellations'
    __table_args__=(CheckConstraint('receivable_waived >= 0 AND refundable_amount >= 0',name='ck_cancellation_amounts'),)
    sale_id: Mapped[int] = mapped_column(ForeignKey('sales.id'),primary_key=True,autoincrement=False)
    merchant_id: Mapped[int] = mapped_column(ForeignKey('merchants.id'))
    shop_id: Mapped[int | None] = mapped_column(ForeignKey('shops.id'),nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey('merchant_users.id'),nullable=True)
    receivable_waived: Mapped[int] = mapped_column(Integer)
    refundable_amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(1000))
    cancelled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow)

class CustomerRefund(Base):
    __tablename__='customer_refunds'
    __table_args__=(UniqueConstraint('merchant_id','shop_id','request_key',name='uq_customer_refund_key'),CheckConstraint('amount > 0',name='ck_customer_refund_positive'))
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey('merchants.id'))
    shop_id: Mapped[int] = mapped_column(ForeignKey('shops.id'))
    sale_id: Mapped[int] = mapped_column(ForeignKey('sale_cancellations.sale_id'))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey('merchant_users.id'))
    amount: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str | None] = mapped_column(String(100),nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow)
    request_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))

class RefundAllocation(Base):
    __tablename__='refund_allocations'
    __table_args__=(CheckConstraint('amount > 0',name='ck_refund_allocation_positive'),)
    refund_id: Mapped[int] = mapped_column(ForeignKey('customer_refunds.id'),primary_key=True,autoincrement=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey('payments.id'),primary_key=True,autoincrement=False)
    amount: Mapped[int] = mapped_column(Integer)
