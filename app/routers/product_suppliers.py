from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.models.product_supplier import ProductSupplier
from app.models.supplier import Supplier
from app.schemas.product_supplier import (
    ProductSupplierCreate,
    ProductSupplierRead,
)

router = APIRouter(tags=["produits-fournisseurs"])


@router.get(
    "/products/{product_id}/suppliers",
    response_model=list[ProductSupplierRead],
)
def list_product_suppliers(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produit introuvable",
        )

    return (
        db.query(ProductSupplier)
        .filter(ProductSupplier.product_id == product_id)
        .order_by(ProductSupplier.is_preferred.desc(), ProductSupplier.id.asc())
        .all()
    )


@router.post(
    "/products/{product_id}/suppliers",
    response_model=ProductSupplierRead,
)
def associate_product_supplier(
    product_id: int,
    payload: ProductSupplierCreate,
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produit introuvable",
        )

    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == payload.supplier_id)
        .first()
    )
    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Fournisseur introuvable",
        )

    existing = (
        db.query(ProductSupplier)
        .filter(
            ProductSupplier.product_id == product_id,
            ProductSupplier.supplier_id == payload.supplier_id,
        )
        .first()
    )

    if payload.is_preferred:
        (
            db.query(ProductSupplier)
            .filter(
                ProductSupplier.product_id == product_id,
                ProductSupplier.supplier_id != payload.supplier_id,
            )
            .update({"is_preferred": False})
        )

    if existing:
        existing.last_purchase_price = max(
            0,
            int(payload.last_purchase_price),
        )
        existing.is_preferred = bool(payload.is_preferred)

        db.commit()
        db.refresh(existing)
        return existing

    association = ProductSupplier(
        product_id=product_id,
        supplier_id=payload.supplier_id,
        last_purchase_price=max(
            0,
            int(payload.last_purchase_price),
        ),
        is_preferred=bool(payload.is_preferred),
    )

    db.add(association)
    db.commit()
    db.refresh(association)

    return association
