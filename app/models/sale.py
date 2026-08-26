from datetime import datetime, date
from sqlalchemy import Integer, ForeignKey, DateTime, String, Date, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.hybrid import hybrid_property
from app.db.base import Base


class Sale(Base):
    __tablename__ = "sales"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "sale_number",
            name="uq_sales_merchant_sale_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    # Numéro visible propre à chaque commerçant.
    # `id` reste la clé technique globale.
    sale_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    paid_amount: Mapped[int] = mapped_column(Integer, default=0)
    remaining_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="credit")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


    @hybrid_property
    def reference_number(self) -> int:
        """
        Numéro communiqué au commerçant.

        Les anciennes fixtures sans sale_number retombent sur l'id
        technique afin de conserver la compatibilité des tests.
        """
        if self.sale_number is not None:
            return self.sale_number
        return self.id

    @reference_number.expression
    def reference_number(cls):
        return func.coalesce(
            cls.sale_number,
            cls.id,
        )
