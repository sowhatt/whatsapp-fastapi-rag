from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.online.public import (
    read_public_catalog,
    read_public_product,
    read_public_store,
    create_cart,
    read_cart,
    set_cart_item,
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


class CartItemPayload(BaseModel):
    product_id: int
    quantity: int = Field(ge=0, le=999)


@router.post("/{slug}/cart", status_code=201)
def storefront_create_cart(
    slug: str,
    db: Session = Depends(get_db),
):
    payload = create_cart(slug=slug, db=db)
    if payload is None:
        raise HTTPException(status_code=404, detail="Boutique introuvable")
    return payload


@router.get("/{slug}/cart/{token}")
def storefront_read_cart(
    slug: str,
    token: str,
    db: Session = Depends(get_db),
):
    payload = read_cart(slug=slug, token=token, db=db)
    if payload is None:
        raise HTTPException(status_code=404, detail="Panier introuvable ou expiré")
    return payload


@router.put("/{slug}/cart/{token}/items")
def storefront_set_cart_item(
    slug: str,
    token: str,
    item: CartItemPayload,
    db: Session = Depends(get_db),
):
    try:
        payload = set_cart_item(
            slug=slug,
            token=token,
            product_id=item.product_id,
            quantity=item.quantity,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload is None:
        raise HTTPException(status_code=404, detail="Panier introuvable ou expiré")
    return payload
