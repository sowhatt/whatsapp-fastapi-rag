from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class PhotoSaleRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_number: int = Field(strict=True, ge=1, le=150)
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


class PhotoSaleConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    shop_id: int = Field(strict=True, gt=0)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    affect_stock: StrictBool
    rows: list[PhotoSaleRow] = Field(min_length=1, max_length=150)
