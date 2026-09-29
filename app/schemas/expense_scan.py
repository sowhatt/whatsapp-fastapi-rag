from pydantic import BaseModel, Field


class ExpenseScanResult(BaseModel):
    merchant_name: str | None = None
    document_date: str | None = None
    amount: int | None = Field(default=None, ge=0)
    currency: str | None = None
    category: str | None = None
    payment_channel: str | None = None
    reference: str | None = None
    note: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExpenseScanResponse(BaseModel):
    result: ExpenseScanResult
    requires_confirmation: bool = True
