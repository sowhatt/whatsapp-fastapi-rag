"""Jeu de démonstration Online : une vitrine de test avec les trois modes de stock.

Ne touche JAMAIS à un commerçant réel : il ne crée / ne met à jour que le commerçant de
démonstration identifié par son numéro. Sans --apply, il n'écrit rien (aperçu).

    DATABASE_URL=... python -B -m scripts.online_demo_seed            # aperçu
    DATABASE_URL=... python -B -m scripts.online_demo_seed --apply    # écriture
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.domains.online.internal.catalog_service import publish_product
from app.domains.online.internal.stock_settings import (
    update_product_stock_settings,
    update_store_stock_settings,
)
from app.domains.online.internal.store_service import get_or_create_store, update_store
from app.models.category import Category
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory

DEMO_NUMBER = "+22900000099"
DEMO_SHOP_NAME = "Boutique démo Online"
DEMO_SLUG = "demo-whatzabi"

# (nom, catégorie, prix, stock Shop, mode, quantité du jour)
PRODUCTS = [
    ("Riz parfumé 25 kg", "Épicerie", 19500, 12, "tracked", None),
    ("Huile végétale 5 L", "Épicerie", 6500, 2, "tracked", None),          # dernières unités
    ("Jus de bissap 1 L", "Boissons", 1500, 0, "daily", 20),
    ("Pain de mie", "Épicerie", 800, 0, "daily", 40),
    ("Couture sur mesure", "Services", 15000, 0, "unlimited", None),
]


def seed_demo(db: Session, *, number: str = DEMO_NUMBER) -> dict:
    merchant = db.query(Merchant).filter(Merchant.whatsapp_number == number).first()
    if merchant is not None and merchant.shop_name != DEMO_SHOP_NAME:
        raise ValueError(
            "Ce numéro appartient à un commerçant réel : la démo ne le modifie jamais."
        )
    if merchant is None:
        merchant = Merchant(whatsapp_number=number, shop_name=DEMO_SHOP_NAME)
        db.add(merchant)
        db.commit()
        db.refresh(merchant)

    shop = db.query(Shop).filter(Shop.merchant_id == merchant.id, Shop.code == "DEMO").first()
    if shop is None:
        shop = Shop(merchant_id=merchant.id, name="Boutique démo", code="DEMO")
        db.add(shop)
        db.commit()
        db.refresh(shop)

    categories = {}
    for name in sorted({row[1] for row in PRODUCTS}):
        category = db.query(Category).filter(
            Category.merchant_id == merchant.id, Category.name == name).first()
        if category is None:
            category = Category(merchant_id=merchant.id, name=name)
            db.add(category)
            db.commit()
            db.refresh(category)
        categories[name] = category.id

    store = get_or_create_store(
        merchant_id=merchant.id, db=db, slug=DEMO_SLUG, display_name="Démo Whatzabi")
    update_store(merchant_id=merchant.id, db=db, description="Boutique de démonstration",
                 city="Cotonou", address="Marché Dantokpa")
    update_store_stock_settings(merchant_id=merchant.id, db=db, fulfilment_shop_id=shop.id)

    published = []
    for name, category, price, stock, mode, daily in PRODUCTS:
        product = db.query(Product).filter(
            Product.merchant_id == merchant.id, Product.name == name).first()
        if product is None:
            product = Product(
                merchant_id=merchant.id, name=name, unit="Pièce", price=price,
                purchase_price=int(price * 0.7), stock=0, initial_stock=0, threshold=0,
                category_id=categories[category])
            db.add(product)
            db.commit()
            db.refresh(product)
        inventory = db.query(ShopInventory).filter(
            ShopInventory.shop_id == shop.id, ShopInventory.product_id == product.id).first()
        if inventory is None:
            db.add(ShopInventory(merchant_id=merchant.id, shop_id=shop.id,
                                 product_id=product.id, stock=stock))
            db.commit()
        publish_product(merchant_id=merchant.id, product_id=product.id, db=db)
        update_product_stock_settings(
            merchant_id=merchant.id, product_id=product.id, db=db,
            stock_mode=mode, daily_quantity=daily)
        published.append(name)
    return {"merchant_id": merchant.id, "slug": store.slug, "products": published,
            "url_path": f"/shop/{store.slug}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="écrit réellement en base")
    parser.add_argument("--number", default=DEMO_NUMBER)
    args = parser.parse_args(argv)
    print(f"Commerçant de démonstration : {args.number} ({DEMO_SHOP_NAME}), vitrine /shop/{DEMO_SLUG}")
    for name, category, price, stock, mode, daily in PRODUCTS:
        extra = f", {daily}/jour" if daily else (f", stock {stock}" if mode == "tracked" else "")
        print(f"  - {name} [{category}] {price} XOF, mode {mode}{extra}")
    if not args.apply:
        print("Aperçu seulement. Relancez avec --apply pour écrire.")
        return 0
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        try:
            result = seed_demo(db, number=args.number)
        except ValueError as exc:
            print(f"Refusé : {exc}", file=sys.stderr)
            return 2
    print(f"Écrit. Vitrine : {result['url_path']} (commerçant {result['merchant_id']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
