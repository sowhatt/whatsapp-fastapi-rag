from pydantic import BaseModel


class ProductCreate(BaseModel):
    category_id: int | None = None
    name: str
    brand: str | None = None
    variant: str | None = None
    packaging: str | None = None
    unit: str
    stock: int = 0
    price: int = 0
    threshold: int = 0


class ProductUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = None
    brand: str | None = None
    variant: str | None = None
    packaging: str | None = None
    unit: str | None = None
    stock: int | None = None
    price: int | None = None
    threshold: int | None = None


class ProductRead(BaseModel):
    id: int
    category_id: int | None
    name: str
    brand: str | None
    variant: str | None
    packaging: str | None
    unit: str
    stock: int
    price: int
    threshold: int

    model_config = {"from_attributes": True}
