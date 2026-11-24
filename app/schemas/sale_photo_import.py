from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class PhotoSaleRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_number: int = Field(strict=True, ge=1, le=150)
    sale_date: date
    sale_group: str = Field(min_length=1, max_length=40)
    product_id: int = Field(strict=True, gt=0)
    quantity: int = Field(strict=True, gt=0, le=1_000_000)
    unit_price: int = Field(strict=True, gt=0, le=2_000_000_000)
    line_total: int = Field(strict=True, gt=0, le=2_000_000_000)
    paid_amount: int = Field(strict=True, ge=0, le=2_000_000_000)
    customer_id: int | None = Field(default=None, gt=0)
    payment_channel: Literal[
        "cash", "mobile_money", "card", "bank_transfer"
    ] | None = None


class DailyTotal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sale_date: date
    total: int = Field(strict=True, ge=0, le=2_000_000_000)


class PhotoSaleConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: UUID
    confirmed: Literal[True]
    shop_id: int = Field(strict=True, gt=0)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_date: date | None = None
    document_total: int | None = Field(ge=0, le=2_000_000_000, strict=True)
    daily_totals: list[DailyTotal] = Field(default_factory=list, max_length=150)
    total_justification: str | None = Field(default=None, min_length=10, max_length=1000)
    duplicate_justification: str | None = Field(default=None, min_length=10, max_length=1000)
    stock_justification: str | None = Field(default=None, min_length=10, max_length=1000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    affect_stock: StrictBool
    rows: list[PhotoSaleRow] = Field(min_length=1, max_length=150)
