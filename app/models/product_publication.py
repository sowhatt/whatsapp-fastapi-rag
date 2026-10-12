from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductPublication(Base):
    __tablename__ = "product_publications"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "product_id",
            name="uq_product_publication_merchant_product",
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

    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    show_price: Mapped[bool] = mapped_column(Boolean, default=True)
    show_stock: Mapped[bool] = mapped_column(Boolean, default=False)

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    display_order: Mapped[int] = mapped_column(Integer, default=0)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
