from pydantic import BaseModel, Field


class SmartCatalogCandidate(BaseModel):
    name: str
    brand: str | None = None
    variant: str | None = None
    packaging: str | None = None
    unit: str | None = None
    barcode: str | None = None
    purchase_price: int | None = None
    quantity: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SmartCatalogMatch(BaseModel):
    product_id: int
    name: str
    score: float = Field(ge=0.0, le=1.0)


class SmartCatalogAnalyzeResponse(BaseModel):
    source: str
    candidates: list[SmartCatalogCandidate]
    matches: dict[int, list[SmartCatalogMatch]] = {}
    requires_confirmation: bool = True
