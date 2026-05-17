from pydantic import BaseModel


class SupplierCreate(BaseModel):
    name: str
    phone: str | None = None
    debt: int = 0


class SupplierRead(BaseModel):
    id: int
    name: str
    phone: str | None = None
    debt: int

    model_config = {"from_attributes": True}