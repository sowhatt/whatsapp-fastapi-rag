from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("uq_suppliers_unassigned_name", "merchant_id", "name", unique=True,
              postgresql_where=text("shop_id IS NULL"), sqlite_where=text("shop_id IS NULL")),
        UniqueConstraint("merchant_id", "shop_id", "name", name="uq_suppliers_merchant_shop_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    debt: Mapped[int] = mapped_column(Integer, default=0)