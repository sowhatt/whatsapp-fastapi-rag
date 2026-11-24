from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, computed_field
from uuid import UUID


class PurchaseItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(strict=True, gt=0)
    quantity: int = Field(strict=True, gt=0, le=1000000)
    unit_cost: int = Field(strict=True, ge=0, le=2000000000)
    # Conserve le total exact de la ligne lorsque le coût unitaire
    # ne permet pas de le reconstruire sans écart d'arrondi.
    line_total: int | None = Field(default=None, strict=True, ge=0, le=2000000000)


class PurchaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID | None = None
    shop_id: int | None = Field(default=None, strict=True, gt=0)
    supplier_id: int | None = Field(default=None, strict=True, gt=0)
    paid_at: datetime | None = None
    items: list[PurchaseItemCreate] = Field(min_length=1, max_length=150)
    paid_amount: int = Field(default=0, strict=True, ge=0, le=2000000000)
    payment_channel: str = "cash"
    due_date: date | None = None

    # total_amount sera toujours recalculé dans la devise comptable de la boutique.
    original_amount: int | None = None
    original_currency: str = "XOF"
    exchange_rate: Decimal | None = None


class PurchaseRead(BaseModel):
    initial_paid_amount: int | None = None
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

    @computed_field
    @property
    def initial_credit_amount(self) -> int | None:
        if self.initial_paid_amount is None:
            return None
        return self.total_amount - self.initial_paid_amount

    @computed_field
    @property
    def subsequent_paid_amount(self) -> int | None:
        if self.initial_paid_amount is None:
            return None
        return self.paid_amount - self.initial_paid_amount

    model_config = {"from_attributes": True}


class CancelPurchasePayload(BaseModel):
    reason: str