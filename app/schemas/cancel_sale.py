from pydantic import BaseModel


class CancelSalePayload(BaseModel):
    reason: str