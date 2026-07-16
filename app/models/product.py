from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    product_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    packaging: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str] = mapped_column(String(30))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    purchase_price: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[int] = mapped_column(Integer, default=0)
    threshold: Mapped[int] = mapped_column(Integer, default=0)
