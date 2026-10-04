from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.online.public import (
    read_public_catalog,
    read_public_product,
    read_public_product_by_slug,
    read_public_store,
    create_cart,
    read_cart,
    set_cart_item,
    checkout_cart,
    read_public_order,
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


@router.get("/{slug}/p/{product_slug}")
def storefront_product_by_slug(
    slug: str,
    product_slug: str,
    db: Session = Depends(get_db),
):
    payload = read_public_product_by_slug(
        slug=slug,
        product_slug=product_slug,
        db=db,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Produit introuvable")
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


class CheckoutPayload(BaseModel):
    customer_name: str = Field(min_length=1, max_length=150)
    customer_phone: str = Field(min_length=3, max_length=40)
    delivery_mode: str = Field(default="pickup")
    delivery_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


@router.post("/{slug}/cart/{token}/checkout", status_code=201)
def storefront_checkout(
    slug: str,
    token: str,
    payload: CheckoutPayload,
    db: Session = Depends(get_db),
):
    try:
        result = checkout_cart(
            slug=slug,
            token=token,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            delivery_mode=payload.delivery_mode,
            delivery_address=payload.delivery_address,
            notes=payload.notes,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Panier ou boutique introuvable")
    return result


@router.get("/{slug}/orders/{reference}")
def storefront_order_status(
    slug: str,
    reference: str,
    phone: str = Query(min_length=3, max_length=40),
    db: Session = Depends(get_db),
):
    result = read_public_order(
        slug=slug,
        reference=reference,
        phone=phone,
        db=db,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Commande introuvable")
    return result
