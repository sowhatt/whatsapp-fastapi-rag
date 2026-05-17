from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    unit: str
    stock: int = 0
    price: int = 0
    threshold: int = 0


class ProductRead(BaseModel):
    id: int
    name: str
    unit: str
    stock: int
    price: int
    threshold: int

    model_config = {"from_attributes": True}