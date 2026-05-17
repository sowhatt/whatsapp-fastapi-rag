from pydantic import BaseModel


class SaleItemCreate(BaseModel):
    product_id: int
    quantity: int


class SaleCreate(BaseModel):
    customer_id: int
    items: list[SaleItemCreate]
    paid_amount: int = 0
    payment_channel: str = "cash"


class SaleRead(BaseModel):
    id: int
    customer_id: int | None
    total_amount: int
    paid_amount: int
    remaining_amount: int
    status: str

    model_config = {"from_attributes": True}