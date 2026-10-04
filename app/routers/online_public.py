from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.online.public import (
    read_public_catalog,
    read_public_product,
    read_public_store,
)


router = APIRouter(prefix="/online", tags=["online-public"])


@router.get("/{slug}")
def storefront(slug: str, db: Session = Depends(get_db)):
    payload = read_public_store(slug=slug, db=db)
    if payload is None:
        raise HTTPException(status_code=404, detail="Boutique introuvable")
    return payload


@router.get("/{slug}/catalog")
def storefront_catalog(
    slug: str,
    category_id: int | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    payload = read_public_catalog(
        slug=slug,
        db=db,
        category_id=category_id,
        query=q,
        limit=limit,
        offset=offset,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Boutique introuvable")
    return payload


@router.get("/{slug}/products/{product_id}")
def storefront_product(
    slug: str,
    product_id: int,
    db: Session = Depends(get_db),
):
    payload = read_public_product(
        slug=slug,
        product_id=product_id,
        db=db,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return payload
