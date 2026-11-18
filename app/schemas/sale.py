from datetime import date, datetime

from pydantic import BaseModel, field_validator
from app.services.finance_time import aware


class SaleItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: int | None = None
    line_total: int | None = None


class SaleCreate(BaseModel):
    occurred_at: datetime | None = None
    _occurred = field_validator("occurred_at")(aware)
    customer_id: int | None = None
    items: list[SaleItemCreate]
    paid_amount: int = 0
    payment_channel: str = "cash"
    due_date: date | None = None

    # Identifiant immuable généré côté PWA pour une vente offline.
    # None pour les ventes online classiques.
    offline_sale_id: str | None = None


class OfflineSaleSyncCreate(BaseModel):
    shop_id: int
    sale: SaleCreate


class SaleRead(BaseModel):
    currency_code: str | None = None
    id: int
    sale_number: int | None = None
    customer_id: int | None
    total_amount: int
    paid_amount: int
    remaining_amount: int
    status: str
    due_date: date | None = None
    offline_sale_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
