from pydantic import BaseModel


class ProductCreate(BaseModel):
    category_id: int | None = None
    name: str
    product_type: str | None = None
    brand: str | None = None
    variant: str | None = None
    packaging: str | None = None
    unit: str
    stock: int = 0
    purchase_price: int = 0
    price: int = 0
    threshold: int = 0


class ProductUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = None
    product_type: str | None = None
    brand: str | None = None
    variant: str | None = None
    packaging: str | None = None
    unit: str | None = None
    stock: int | None = None
    purchase_price: int | None = None
    price: int | None = None
    threshold: int | None = None


class ProductRead(BaseModel):
    id: int
    category_id: int | None
    name: str
    product_type: str | None
    brand: str | None
    variant: str | None
    packaging: str | None
    unit: str
    stock: int
    purchase_price: int
    price: int
    threshold: int

    model_config = {"from_attributes": True}
