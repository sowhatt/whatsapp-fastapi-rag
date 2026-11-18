from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from app.services.finance_time import aware


class PaymentCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    effective_at: datetime | None = None
    _effective = field_validator('effective_at')(aware)
    sale_id: int
    customer_id: int | None = None
    amount: int
    channel: str
    reference: str | None = None


class PaymentRead(BaseModel):
    currency_code: str | None = None
    idempotency_key: str | None = None
    merchant_id: int | None = None
    shop_id: int | None = None
    effective_at: datetime | None = None
    effective_at_source: str | None = None
    allocations: list[dict] | None = None
    id: int
    sale_id: int
    customer_id: int | None
    amount: int
    channel: str
    reference: str | None = None

    model_config = {"from_attributes": True}