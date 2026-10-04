from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.online.internal.store_service import get_public_store
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_publication import ProductPublication
from app.services.customer_catalog_service import (
    list_customer_catalog,
    search_customer_catalog,
)


router = APIRouter(prefix="/online", tags=["online-public"])


def _store_payload(store):
    return {
        "slug": store.slug,
        "display_name": store.display_name,
        "description": store.description,
        "logo_url": store.logo_url,
        "banner_url": store.banner_url,
        "primary_color": store.primary_color,
        "accent_color": store.accent_color,
        "template": store.template,
        "currency": store.currency,
        "country_code": store.country_code,
    }


@router.get("/{slug}")
def storefront(slug: str, db: Session = Depends(get_db)):
    store = get_public_store(slug=slug, db=db)
    if store is None:
        raise HTTPException(status_code=404, detail="Boutique introuvable")
    return _store_payload(store)


@router.get("/{slug}/catalog")
def storefront_catalog(
    slug: str,
    category_id: int | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    store = get_public_store(slug=slug, db=db)
    if store is None:
        raise HTTPException(status_code=404, detail="Boutique introuvable")

    if q:
        products = search_customer_catalog(
            merchant_id=store.merchant_id,
            query=q,
            db=db,
            limit=min(limit, 50),
        )
    else:
        products = list_customer_catalog(
            merchant_id=store.merchant_id,
            db=db,
            category_id=category_id,
            limit=limit,
            offset=offset,
        )

    return {
        "store": _store_payload(store),
        "products": products,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{slug}/products/{product_id}")
def storefront_product(
    slug: str,
    product_id: int,
    db: Session = Depends(get_db),
):
    store = get_public_store(slug=slug, db=db)
    if store is None:
        raise HTTPException(status_code=404, detail="Boutique introuvable")

    row = (
        db.query(Product, ProductPublication)
        .join(
            ProductPublication,
            ProductPublication.product_id == Product.id,
        )
        .filter(
            Product.id == product_id,
            Product.merchant_id == store.merchant_id,
            ProductPublication.merchant_id == store.merchant_id,
            ProductPublication.is_published.is_(True),
            ProductPublication.is_active.is_(True),
        )
        .first()
    )

    if row is None:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    product, publication = row
    image = (
        db.query(ProductImage)
        .filter(
            ProductImage.merchant_id == store.merchant_id,
            ProductImage.product_id == product.id,
        )
        .order_by(
            ProductImage.is_primary.desc(),
            ProductImage.position,
            ProductImage.id,
        )
        .first()
    )

    return {
        "id": product.id,
        "name": product.name,
        "unit": product.unit,
        "price": product.price if publication.show_price else None,
        "available": product.stock > 0,
        "stock": product.stock if publication.show_stock else None,
        "description": publication.description,
        "image_url": image.image_url if image else None,
        "currency": store.currency,
    }
