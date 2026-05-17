from pydantic import BaseModel


class PaymentCreate(BaseModel):
    sale_id: int
    customer_id: int | None = None
    amount: int
    channel: str
    reference: str | None = None


class PaymentRead(BaseModel):
    id: int
    sale_id: int
    customer_id: int | None
    amount: int
    channel: str
    reference: str | None = None

    model_config = {"from_attributes": True}