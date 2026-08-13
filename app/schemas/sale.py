from datetime import date

from pydantic import BaseModel


class SaleItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: int | None = None
    line_total: int | None = None


class SaleCreate(BaseModel):
    customer_id: int
    items: list[SaleItemCreate]
    paid_amount: int = 0
    payment_channel: str = "cash"
    due_date: date | None = None


class SaleRead(BaseModel):
    id: int
    customer_id: int | None
    total_amount: int
    paid_amount: int
    remaining_amount: int
    status: str
    due_date: date | None = None

    model_config = {"from_attributes": True}
