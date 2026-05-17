from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductRead

router = APIRouter(tags=["produits"])


@router.get("/products", response_model=list[ProductRead])
def list_products(db: Session = Depends(get_db)):
    """Liste tous les produits du catalogue."""
    return db.query(Product).all()


@router.post("/products", response_model=ProductRead)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """Crée un produit avec son stock initial, son prix et son seuil d’alerte."""
    existing = db.query(Product).filter(Product.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce produit existe déjà")

    product = Product(
        name=payload.name,
        unit=payload.unit,
        stock=payload.stock,
        price=payload.price,
        threshold=payload.threshold,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product