from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.core.public.stock import available_stock
from app.domains.online.internal.catalog_models import (
    OnlineProductImage,
    OnlineProductPublication,
)
from app.domains.online.internal.store_service import normalize_store_slug
from app.models.category import Category
from app.models.product import Product


def publish_product(
    *,
    merchant_id: int,
    product_id: int,
    db: Session,
    description: str | None = None,
    show_stock: bool = False,
    seo_slug: str | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
) -> OnlineProductPublication:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.merchant_id == merchant_id,
    ).first()
    if product is None:
        raise ValueError("Produit introuvable pour ce commerce.")

    publication = db.query(OnlineProductPublication).filter(
        OnlineProductPublication.merchant_id == merchant_id,
        OnlineProductPublication.product_id == product_id,
    ).first()
    if publication is None:
        publication = OnlineProductPublication(
            merchant_id=merchant_id,
            product_id=product_id,
        )
        db.add(publication)

    publication.is_published = True
    publication.is_active = True
    publication.show_price = True
    publication.show_stock = show_stock
    if description is not None:
        publication.description = description

    try:
        candidate_slug = normalize_store_slug(seo_slug or product.name)
    except ValueError:
        candidate_slug = f"produit-{product_id}"

    collision = db.query(OnlineProductPublication).filter(
        OnlineProductPublication.merchant_id == merchant_id,
        OnlineProductPublication.seo_slug == candidate_slug,
        OnlineProductPublication.product_id != product_id,
    ).first()
    if collision is not None:
        candidate_slug = normalize_store_slug(f"{candidate_slug}-{product_id}")

    publication.seo_slug = candidate_slug
    publication.seo_title = (seo_title or product.name)[:180]
    publication.seo_description = (
        seo_description or description or f"Achetez {product.name} en ligne."
    )[:320]

    if publication.published_at is None:
        publication.published_at = datetime.now(UTC)

    db.commit()
    db.refresh(publication)
    return publication


def unpublish_product(*, merchant_id: int, product_id: int, db: Session) -> None:
    publication = db.query(OnlineProductPublication).filter(
        OnlineProductPublication.merchant_id == merchant_id,
        OnlineProductPublication.product_id == product_id,
    ).first()
    if publication is None:
        return
    publication.is_published = False
    db.commit()


def add_product_image(
    *,
    merchant_id: int,
    product_id: int,
    image_url: str,
    db: Session,
    storage_key: str | None = None,
    is_primary: bool = False,
) -> OnlineProductImage:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.merchant_id == merchant_id,
    ).first()
    if product is None:
        raise ValueError("Produit introuvable pour ce commerce.")

    if is_primary:
        db.query(OnlineProductImage).filter(
            OnlineProductImage.merchant_id == merchant_id,
            OnlineProductImage.product_id == product_id,
            OnlineProductImage.is_primary.is_(True),
        ).update({"is_primary": False})

    image = OnlineProductImage(
        merchant_id=merchant_id,
        product_id=product_id,
        image_url=image_url,
        storage_key=storage_key,
        is_primary=is_primary,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def _catalog_query(*, merchant_id: int, db: Session):
    return (
        db.query(Product, OnlineProductPublication)
        .join(
            OnlineProductPublication,
            OnlineProductPublication.product_id == Product.id,
        )
        .filter(
            Product.merchant_id == merchant_id,
            OnlineProductPublication.merchant_id == merchant_id,
            OnlineProductPublication.is_published.is_(True),
            OnlineProductPublication.is_active.is_(True),
        )
    )


def _serialize_product(*, product: Product, publication: OnlineProductPublication, merchant_id: int, db: Session) -> dict[str, Any]:
    image = db.query(OnlineProductImage).filter(
        OnlineProductImage.merchant_id == merchant_id,
        OnlineProductImage.product_id == product.id,
    ).order_by(
        OnlineProductImage.is_primary.desc(),
        OnlineProductImage.position,
        OnlineProductImage.id,
    ).first()

    category = None
    if product.category_id:
        category = db.query(Category).filter(
            Category.id == product.category_id,
            Category.merchant_id == merchant_id,
        ).first()

    current_available = available_stock(product=product, db=db)
    return {
        "id": product.id,
        "name": product.name,
        "unit": product.unit,
        "price": product.price if publication.show_price else None,
        "available": current_available > 0,
        "stock": current_available if publication.show_stock else None,
        "description": publication.description,
        "category": category.name if category else None,
        "image_url": image.image_url if image else None,
        "seo_slug": publication.seo_slug,
        "seo_title": publication.seo_title,
        "seo_description": publication.seo_description,
    }


def list_online_catalog(
    *,
    merchant_id: int,
    db: Session,
    category_id: int | None = None,
    limit: int = 24,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = _catalog_query(merchant_id=merchant_id, db=db)
    if category_id is not None:
        query = query.filter(Product.category_id == category_id)

    rows = query.order_by(
        OnlineProductPublication.display_order,
        Product.name,
    ).offset(offset).limit(limit).all()

    return [
        _serialize_product(
            product=product,
            publication=publication,
            merchant_id=merchant_id,
            db=db,
        )
        for product, publication in rows
    ]


def search_online_catalog(
    *,
    merchant_id: int,
    query: str,
    db: Session,
    limit: int = 24,
) -> list[dict[str, Any]]:
    normalized = " ".join(query.split()).strip()
    if not normalized:
        return []

    rows = _catalog_query(merchant_id=merchant_id, db=db).filter(
        func.lower(Product.name).contains(normalized.lower())
    ).order_by(Product.name).limit(limit).all()

    return [
        _serialize_product(
            product=product,
            publication=publication,
            merchant_id=merchant_id,
            db=db,
        )
        for product, publication in rows
    ]
