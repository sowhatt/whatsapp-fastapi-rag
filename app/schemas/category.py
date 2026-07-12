from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str


class CategoryRead(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}
