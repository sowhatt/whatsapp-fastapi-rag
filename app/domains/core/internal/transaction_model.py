from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BusinessTransaction(Base):
    """Shared transaction root for new Whatzabi verticals.

    It is additive: legacy Sale/Purchase models are not replaced or modified.
    A vertical aggregate references this root when it adopts the new model.
    """

    __tablename__ = "business_transactions"
    __table_args__ = (
        Index(
            "ix_business_transactions_merchant_created_at",
            "merchant_id",
            "created_at",
        ),
        Index(
            "ix_business_transactions_merchant_kind_status",
            "merchant_id",
            "kind",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"),
        nullable=False,
        index=True,
    )
    # Kept nullable until Shop becomes a first-class shared entity everywhere.
    shop_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF")

    subtotal_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fee_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    payment_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="unpaid",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
