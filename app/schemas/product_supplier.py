from pydantic import BaseModel


class ProductSupplierCreate(BaseModel):
    supplier_id: int
    last_purchase_price: int = 0
    is_preferred: bool = False


class ProductSupplierRead(BaseModel):
    id: int
    product_id: int
    supplier_id: int
    last_purchase_price: int
    is_preferred: bool

    model_config = {"from_attributes": True}
