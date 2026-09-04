from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.db.session import get_db
from app.models.category import Category
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.shop_context_service import (
    get_current_shop_id,
    get_effective_stock,
    set_initial_shop_stock,
)

router = APIRouter(tags=["produits"])


def _apply_shop_stock_view(products: list[Product], db: Session) -> list[Product]:
    if get_current_shop_id(db) is None:
        return products
    for product in products:
        set_committed_value(product, "stock", get_effective_stock(product, db))
    return products


@router.get("/products", response_model=list[ProductRead])
def list_products(
    category_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Product)
    if category_id is not None:
        query = query.filter(Product.category_id == category_id)
    products = query.order_by(Product.name.asc()).all()
    return _apply_shop_stock_view(products, db)


@router.post("/products", response_model=ProductRead)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    name = " ".join(payload.name.split()).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom du produit est obligatoire")
    if payload.price < 0 or payload.purchase_price < 0:
        raise HTTPException(status_code=400, detail="Les prix doivent être positifs")

    existing = db.query(Product).filter(func.lower(Product.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce produit existe déjà")

    if payload.category_id is not None and not db.get(Category, payload.category_id):
        raise HTTPException(status_code=404, detail="Catégorie introuvable")

    shop_id = get_current_shop_id(db)
    product = Product(
        category_id=payload.category_id,
        name=name[:1].upper() + name[1:],
        product_type=payload.product_type,
        brand=payload.brand,
        variant=payload.variant,
        packaging=payload.packaging,
        unit=payload.unit,
        stock=0 if shop_id is not None else payload.stock,
        purchase_price=payload.purchase_price,
        price=payload.price,
        threshold=payload.threshold,
    )
    db.add(product)
    db.flush()

    if shop_id is not None:
        set_initial_shop_stock(product, payload.stock, db)

    db.commit()
    db.refresh(product)
    if shop_id is not None:
        set_committed_value(product, "stock", get_effective_stock(product, db))
    return product


@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    changes = payload.model_dump(exclude_unset=True)
    if "category_id" in changes and changes["category_id"] is not None:
        if not db.get(Category, changes["category_id"]):
            raise HTTPException(status_code=404, detail="Catégorie introuvable")

    for price_field in ("price", "purchase_price"):
        if price_field in changes and changes[price_field] is not None and changes[price_field] < 0:
            raise HTTPException(status_code=400, detail="Les prix doivent être positifs")

    if "name" in changes and changes["name"]:
        new_name = " ".join(changes["name"].split()).strip()
        duplicate = (
            db.query(Product)
            .filter(func.lower(Product.name) == new_name.lower(), Product.id != product_id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Un autre produit porte déjà ce nom")
        changes["name"] = new_name[:1].upper() + new_name[1:]

    shop_id = get_current_shop_id(db)
    requested_stock = changes.pop("stock", None) if shop_id is not None else None

    for field, value in changes.items():
        setattr(product, field, value)

    if shop_id is not None and requested_stock is not None:
        set_initial_shop_stock(product, int(requested_stock), db)

    db.commit()
    db.refresh(product)
    if shop_id is not None:
        set_committed_value(product, "stock", get_effective_stock(product, db))
    return product
