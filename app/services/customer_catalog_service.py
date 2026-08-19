from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_publication import ProductPublication
from app.services.sales_service import find_product_candidates


def _format_currency(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def publish_product(
    *,
    merchant_id: int,
    product_id: int,
    db: Session,
    description: str | None = None,
    show_stock: bool = False,
) -> ProductPublication:
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.merchant_id == merchant_id,
        )
        .first()
    )

    if not product:
        raise ValueError("Produit introuvable pour ce commerce.")

    publication = (
        db.query(ProductPublication)
        .filter(
            ProductPublication.merchant_id == merchant_id,
            ProductPublication.product_id == product_id,
        )
        .first()
    )

    if publication is None:
        publication = ProductPublication(
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

    if publication.published_at is None:
        publication.published_at = datetime.now(UTC)

    db.commit()
    db.refresh(publication)

    return publication


def unpublish_product(
    *,
    merchant_id: int,
    product_id: int,
    db: Session,
) -> None:
    publication = (
        db.query(ProductPublication)
        .filter(
            ProductPublication.merchant_id == merchant_id,
            ProductPublication.product_id == product_id,
        )
        .first()
    )

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
) -> ProductImage:
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.merchant_id == merchant_id,
        )
        .first()
    )

    if not product:
        raise ValueError("Produit introuvable pour ce commerce.")

    if is_primary:
        (
            db.query(ProductImage)
            .filter(
                ProductImage.merchant_id == merchant_id,
                ProductImage.product_id == product_id,
                ProductImage.is_primary.is_(True),
            )
            .update({"is_primary": False})
        )

    image = ProductImage(
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


def list_customer_catalog(
    *,
    merchant_id: int,
    db: Session,
    category_id: int | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = (
        db.query(Product, ProductPublication)
        .join(
            ProductPublication,
            ProductPublication.product_id == Product.id,
        )
        .filter(
            Product.merchant_id == merchant_id,
            ProductPublication.merchant_id == merchant_id,
            ProductPublication.is_published.is_(True),
            ProductPublication.is_active.is_(True),
        )
    )

    if category_id is not None:
        query = query.filter(Product.category_id == category_id)

    rows = (
        query
        .order_by(
            ProductPublication.display_order,
            Product.name,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []

    for product, publication in rows:
        image = (
            db.query(ProductImage)
            .filter(
                ProductImage.merchant_id == merchant_id,
                ProductImage.product_id == product.id,
            )
            .order_by(
                ProductImage.is_primary.desc(),
                ProductImage.position,
                ProductImage.id,
            )
            .first()
        )

        category = None
        if product.category_id:
            category = (
                db.query(Category)
                .filter(
                    Category.id == product.category_id,
                    Category.merchant_id == merchant_id,
                )
                .first()
            )

        result.append(
            {
                "id": product.id,
                "name": product.name,
                "unit": product.unit,
                "price": product.price if publication.show_price else None,
                "available": product.stock > 0,
                "stock": product.stock if publication.show_stock else None,
                "description": publication.description,
                "category": category.name if category else None,
                "image_url": image.image_url if image else None,
            }
        )

    return result


def search_customer_catalog(
    *,
    merchant_id: int,
    query: str,
    db: Session,
    limit: int = 5,
) -> list[dict[str, Any]]:
    normalized = " ".join(query.split()).strip()

    if not normalized:
        return []

    products = (
        db.query(Product)
        .join(
            ProductPublication,
            ProductPublication.product_id == Product.id,
        )
        .filter(
            Product.merchant_id == merchant_id,
            ProductPublication.merchant_id == merchant_id,
            ProductPublication.is_published.is_(True),
            ProductPublication.is_active.is_(True),
            func.lower(Product.name).contains(normalized.lower()),
        )
        .order_by(Product.name)
        .limit(limit)
        .all()
    )

    result = []

    for product in products:
        publication = (
            db.query(ProductPublication)
            .filter(
                ProductPublication.merchant_id == merchant_id,
                ProductPublication.product_id == product.id,
            )
            .first()
        )

        image = (
            db.query(ProductImage)
            .filter(
                ProductImage.merchant_id == merchant_id,
                ProductImage.product_id == product.id,
            )
            .order_by(
                ProductImage.is_primary.desc(),
                ProductImage.position,
                ProductImage.id,
            )
            .first()
        )

        result.append(
            {
                "id": product.id,
                "name": product.name,
                "unit": product.unit,
                "price": product.price if publication.show_price else None,
                "available": product.stock > 0,
                "stock": product.stock if publication.show_stock else None,
                "description": publication.description,
                "image_url": image.image_url if image else None,
            }
        )

    return result


def render_customer_catalog(
    *,
    merchant_id: int,
    db: Session,
    limit: int = 10,
) -> str:
    products = list_customer_catalog(
        merchant_id=merchant_id,
        db=db,
        limit=limit,
    )

    if not products:
        return "Le catalogue ne contient aucun produit disponible pour le moment."

    # merchant_id est passé explicitement par l'appelant (pas de
    # dépendance au contexte tenant implicite ici), on interroge donc
    # directement le Merchant correspondant plutôt que
    # get_current_shop_name (qui suppose set_current_merchant appelé).
    from app.models.merchant import Merchant

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    shop_name = merchant.shop_name if merchant and merchant.shop_name else "Catalogue"
    lines = [f"🛒 {shop_name}", ""]

    for index, product in enumerate(products, start=1):
        price = product.get("price")

        if price is None:
            price_text = "Prix sur demande"
        else:
            price_text = _format_currency(price)

        availability = "✅ Disponible" if product["available"] else "❌ Rupture"

        lines.append(
            f"{index}. {product['name']} — {price_text}"
        )
        lines.append(f"   {availability}")

    lines.extend(
        [
            "",
            "Dis-moi simplement ce que tu cherches.",
        ]
    )

    return "\n".join(lines)
