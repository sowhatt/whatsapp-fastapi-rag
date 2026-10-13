from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.domains.online.foundation import require_business_type, require_capability

from app.domains.online.internal.catalog_models import OnlineProductImage, OnlineProductPublication

from app.domains.online.internal.cart_models import OnlineCart, OnlineCartItem
from app.domains.online.internal.store_service import get_public_store, get_store_capabilities
from app.models.product import Product
from app.domains.core.public.stock import available_stock


def _load_active_cart(*, slug: str, token: str, db: Session) -> tuple[Any, OnlineCart] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None
    require_business_type(store.business_type, "commerce")
    require_capability(get_store_capabilities(store), "cart")

    cart = (
        db.query(OnlineCart)
        .filter(
            OnlineCart.token == token,
            OnlineCart.store_id == store.id,
            OnlineCart.merchant_id == store.merchant_id,
            OnlineCart.status == "active",
        )
        .first()
    )
    if cart is None or cart.expires_at <= datetime.utcnow():
        return None
    return store, cart


def _cart_payload(*, store, cart: OnlineCart, db: Session) -> dict[str, Any]:
    rows = (
        db.query(OnlineCartItem, Product)
        .join(Product, Product.id == OnlineCartItem.product_id)
        .filter(
            OnlineCartItem.cart_id == cart.id,
            OnlineCartItem.merchant_id == store.merchant_id,
        )
        .order_by(OnlineCartItem.id)
        .all()
    )

    items = []
    total = 0
    quantity_total = 0
    for item, product in rows:
        line_total = item.unit_price_snapshot * item.quantity
        total += line_total
        quantity_total += item.quantity
        items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "unit": product.unit,
                "quantity": item.quantity,
                "unit_price": item.unit_price_snapshot,
                "line_total": line_total,
                "available_stock": available_stock(product=product, db=db),
            }
        )

    return {
        "token": cart.token,
        "status": cart.status,
        "currency": cart.currency,
        "items": items,
        "quantity_total": quantity_total,
        "subtotal": total,
        "expires_at": cart.expires_at.isoformat(),
    }


def create_cart(*, slug: str, db: Session) -> dict[str, Any] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None
    require_capability(get_store_capabilities(store), "cart")

    cart = OnlineCart(
        merchant_id=store.merchant_id,
        store_id=store.id,
        currency=store.currency,
        status="active",
    )
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return _cart_payload(store=store, cart=cart, db=db)


def read_cart(*, slug: str, token: str, db: Session) -> dict[str, Any] | None:
    loaded = _load_active_cart(slug=slug, token=token, db=db)
    if loaded is None:
        return None
    store, cart = loaded
    return _cart_payload(store=store, cart=cart, db=db)


def set_cart_item(
    *,
    slug: str,
    token: str,
    product_id: int,
    quantity: int,
    db: Session,
) -> dict[str, Any] | None:
    if quantity < 0:
        raise ValueError("La quantité ne peut pas être négative.")

    loaded = _load_active_cart(slug=slug, token=token, db=db)
    if loaded is None:
        return None
    store, cart = loaded

    product_row = (
        db.query(Product, OnlineProductPublication)
        .join(OnlineProductPublication, OnlineProductPublication.product_id == Product.id)
        .filter(
            Product.id == product_id,
            Product.merchant_id == store.merchant_id,
            OnlineProductPublication.merchant_id == store.merchant_id,
            OnlineProductPublication.is_published.is_(True),
            OnlineProductPublication.is_active.is_(True),
        )
        .first()
    )
    if product_row is None:
        raise ValueError("Produit indisponible sur cette boutique.")

    product, publication = product_row
    if not publication.show_price:
        raise ValueError("Ce produit ne peut pas être commandé en ligne sans prix public.")
    current_available = available_stock(product=product, db=db)
    if quantity > current_available:
        raise ValueError(
            f"Stock disponible insuffisant : {current_available} disponible(s)."
        )

    item = (
        db.query(OnlineCartItem)
        .filter(
            OnlineCartItem.cart_id == cart.id,
            OnlineCartItem.product_id == product.id,
            OnlineCartItem.merchant_id == store.merchant_id,
        )
        .first()
    )

    if quantity == 0:
        if item is not None:
            db.delete(item)
    elif item is None:
        db.add(
            OnlineCartItem(
                merchant_id=store.merchant_id,
                cart_id=cart.id,
                product_id=product.id,
                quantity=quantity,
                unit_price_snapshot=product.price,
            )
        )
    else:
        item.quantity = quantity
        item.unit_price_snapshot = product.price

    cart.updated_at = datetime.utcnow()
    db.commit()
    return _cart_payload(store=store, cart=cart, db=db)
