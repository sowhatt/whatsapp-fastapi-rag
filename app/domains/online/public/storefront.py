from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domains.online.internal.catalog_models import OnlineProductImage, OnlineProductPublication

from app.domains.online.internal.store_service import get_public_store, get_store_capabilities
from app.domains.online.internal.catalog_service import list_online_catalog, search_online_catalog
from app.domains.online.foundation.seo import SeoProfile
from app.models.product import Product
from app.domains.core.public.stock import available_stock


def _store_payload(store) -> dict[str, Any]:
    seo = SeoProfile.for_store(
        business_type=store.business_type,
        display_name=store.display_name,
        description=store.description,
        seo_title=store.seo_title,
        seo_description=store.seo_description,
        canonical_domain=store.canonical_domain,
    )
    return {
        "slug": store.slug,
        "display_name": store.display_name,
        "description": store.description,
        "logo_url": store.logo_url,
        "banner_url": store.banner_url,
        "primary_color": store.primary_color,
        "accent_color": store.accent_color,
        "business_type": store.business_type,
        "capabilities": list(get_store_capabilities(store)),
        "template": store.template,
        "currency": store.currency,
        "country_code": store.country_code,
        "seo_title": seo.title,
        "seo_description": seo.description,
        "canonical_domain": seo.canonical_domain,
        "schema_type": seo.schema_type,
        "address": store.address,
        "city": store.city,
        "postal_code": store.postal_code,
        "latitude": store.latitude,
        "longitude": store.longitude,
    }


def read_public_store(*, slug: str, db: Session) -> dict[str, Any] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None
    return _store_payload(store)


def read_public_catalog(
    *,
    slug: str,
    db: Session,
    category_id: int | None = None,
    query: str | None = None,
    limit: int = 24,
    offset: int = 0,
) -> dict[str, Any] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None

    if query:
        products = search_online_catalog(
            merchant_id=store.merchant_id,
            query=query,
            db=db,
            limit=min(limit, 50),
        )
    else:
        products = list_online_catalog(
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


def read_public_product(
    *,
    slug: str,
    product_id: int,
    db: Session,
) -> dict[str, Any] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None

    row = (
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
    if row is None:
        return None

    product, publication = row
    image = (
        db.query(OnlineProductImage)
        .filter(
            OnlineProductImage.merchant_id == store.merchant_id,
            OnlineProductImage.product_id == product.id,
        )
        .order_by(
            OnlineProductImage.is_primary.desc(),
            OnlineProductImage.position,
            OnlineProductImage.id,
        )
        .first()
    )

    return {
        "id": product.id,
        "name": product.name,
        "unit": product.unit,
        "price": product.price if publication.show_price else None,
        "available": available_stock(product=product, db=db) > 0,
        "stock": (
            available_stock(product=product, db=db)
            if publication.show_stock
            else None
        ),
        "description": publication.description,
        "image_url": image.image_url if image else None,
        "currency": store.currency,
        "seo_slug": publication.seo_slug,
        "seo_title": publication.seo_title or product.name,
        "seo_description": publication.seo_description or publication.description,
    }



def read_public_product_by_slug(
    *,
    slug: str,
    product_slug: str,
    db: Session,
) -> dict[str, Any] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None

    publication = (
        db.query(OnlineProductPublication)
        .filter(
            OnlineProductPublication.merchant_id == store.merchant_id,
            OnlineProductPublication.seo_slug == product_slug,
            OnlineProductPublication.is_published.is_(True),
            OnlineProductPublication.is_active.is_(True),
        )
        .first()
    )
    if publication is None:
        return None

    return read_public_product(
        slug=slug,
        product_id=publication.product_id,
        db=db,
    )
