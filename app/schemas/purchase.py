from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


class PurchaseItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_cost: int


class PurchaseCreate(BaseModel):
    supplier_id: int
    items: list[PurchaseItemCreate]
    paid_amount: int = 0
    payment_channel: str = "cash"
    due_date: date | None = None

    # total_amount sera toujours recalculé dans la devise comptable de la boutique.
    original_amount: int | None = None
    original_currency: str = "XOF"
    exchange_rate: Decimal | None = None


class PurchaseRead(BaseModel):
    id: int
    supplier_id: int | None
    total_amount: int
    paid_amount: int
    remaining_amount: int
    status: str
    original_amount: int | None = None
    original_currency: str = "XOF"
    exchange_rate: Decimal | None = None
    due_date: date | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CancelPurchasePayload(BaseModel):
    reason: str