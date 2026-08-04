from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    debt: Mapped[int] = mapped_column(Integer, default=0)