from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    debt: int = 0


class CustomerRead(BaseModel):
    id: int
    name: str
    phone: str | None = None
    debt: int

    model_config = {"from_attributes": True}