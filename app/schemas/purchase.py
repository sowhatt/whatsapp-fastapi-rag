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


class PurchaseRead(BaseModel):
    id: int
    supplier_id: int | None
    total_amount: int
    paid_amount: int
    remaining_amount: int
    status: str

    model_config = {"from_attributes": True}


class CancelPurchasePayload(BaseModel):
    reason: str