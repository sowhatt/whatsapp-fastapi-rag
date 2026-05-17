from pydantic import BaseModel


class FinancialEntryCreate(BaseModel):
    entry_type: str
    amount: int
    channel: str = "cash"
    label: str
    note: str | None = None


class FinancialEntryRead(BaseModel):
    id: int
    entry_type: str
    amount: int
    channel: str
    label: str
    note: str | None = None
    origin_kind: str
    reference_type: str | None = None
    reference_id: int | None = None

    model_config = {"from_attributes": True}