from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductSupplier(Base):
    __tablename__ = "product_suppliers"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "product_id",
            "supplier_id",
            name="uq_product_suppliers_merchant_product_supplier",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    merchant_id: Mapped[int | None] = mapped_column(
        ForeignKey("merchants.id"),
        nullable=True,
        index=True,
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"),
        nullable=False,
        index=True,
    )

    last_purchase_price: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    is_preferred: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
