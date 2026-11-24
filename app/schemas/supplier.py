from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID | None = None
    shop_id: int | None = Field(default=None, strict=True, gt=0)
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    debt: int = Field(default=0, strict=True, ge=0, le=2000000000)


class SupplierRead(BaseModel):
    shop_id: int | None = None
    id: int
    name: str
    phone: str | None = None
    debt: int

    model_config = {"from_attributes": True}