from pydantic import BaseModel, Field, ConfigDict, field_serializer
from uuid import UUID
from datetime import datetime, timezone


class SupplierPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID | None = None
    shop_id: int | None = Field(default=None, strict=True, gt=0)
    paid_at: datetime | None = None
    purchase_id: int = Field(strict=True, gt=0)
    supplier_id: int | None = Field(default=None, strict=True, gt=0)
    amount: int = Field(strict=True, gt=0, le=2000000000)
    channel: str = Field(min_length=1, max_length=30)
    reference: str | None = Field(default=None, max_length=100)


class SupplierPaymentRead(BaseModel):
    paid_at: datetime
    id: int
    purchase_id: int
    supplier_id: int | None
    amount: int
    channel: str
    reference: str | None = None

    @field_serializer('paid_at')
    def serialize_paid_at(self, value):
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()

    model_config = {"from_attributes": True}