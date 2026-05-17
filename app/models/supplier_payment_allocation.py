from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SupplierPaymentAllocation(Base):
    __tablename__ = "supplier_payment_allocations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    supplier_payment_id: Mapped[int] = mapped_column(ForeignKey("supplier_payments.id"))
    purchase_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_items.id"))
    allocated_amount: Mapped[int] = mapped_column(Integer, default=0)