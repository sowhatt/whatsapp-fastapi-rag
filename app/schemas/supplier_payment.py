from pydantic import BaseModel


class SupplierPaymentCreate(BaseModel):
    purchase_id: int
    supplier_id: int | None = None
    amount: int
    channel: str
    reference: str | None = None


class SupplierPaymentRead(BaseModel):
    id: int
    purchase_id: int
    supplier_id: int | None
    amount: int
    channel: str
    reference: str | None = None

    model_config = {"from_attributes": True}