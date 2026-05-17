from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    sale_item_id: Mapped[int] = mapped_column(ForeignKey("sale_items.id"))
    allocated_amount: Mapped[int] = mapped_column(Integer, default=0)