from sqlalchemy.orm import Session

from app.db.tenant import get_current_merchant
from app.models.product import Product
from app.models.shop_inventory import ShopInventory
from app.models.shop_operation import ShopOperation


def get_current_shop_id(db: Session) -> int | None:
    return db.info.get("pwa_shop_id") or db.info.get("resolved_shop_id")


def get_current_user_id(db: Session) -> int | None:
    return db.info.get("pwa_user_id") or db.info.get("resolved_user_id")


def get_effective_stock(product: Product, db: Session) -> int:
    shop_id = get_current_shop_id(db)
    if shop_id is None:
        return int(product.stock or 0)
    inventory = (
        db.query(ShopInventory)
        .filter(
            ShopInventory.shop_id == shop_id,
            ShopInventory.product_id == product.id,
        )
        .first()
    )
    return int(inventory.stock if inventory is not None else 0)


def adjust_stock(product: Product, quantity_delta: int, db: Session) -> int:
    """Adjust shop stock when a shop is selected; otherwise keep legacy stock behavior."""
    shop_id = get_current_shop_id(db)
    merchant_id = get_current_merchant(db) or getattr(product, "merchant_id", None)
    if shop_id is None:
        product.stock = int(product.stock or 0) + quantity_delta
        return product.stock
    if merchant_id is None:
        raise ValueError("merchant_id requis pour un stock de boutique")

    inventory = (
        db.query(ShopInventory)
        .filter(
            ShopInventory.shop_id == shop_id,
            ShopInventory.product_id == product.id,
        )
        .with_for_update()
        .first()
    )
    if inventory is None:
        inventory = ShopInventory(
            merchant_id=merchant_id,
            shop_id=shop_id,
            product_id=product.id,
            stock=0,
            threshold=int(product.threshold or 0),
        )
        db.add(inventory)
        db.flush()

    new_stock = int(inventory.stock or 0) + quantity_delta
    if new_stock < 0:
        raise ValueError("stock insuffisant")
    inventory.stock = new_stock
    return new_stock


def set_initial_shop_stock(product: Product, stock: int, db: Session) -> None:
    shop_id = get_current_shop_id(db)
    merchant_id = get_current_merchant(db) or getattr(product, "merchant_id", None)
    if shop_id is None:
        product.stock = stock
        return
    if merchant_id is None:
        raise ValueError("merchant_id requis pour un stock de boutique")

    inventory = (
        db.query(ShopInventory)
        .filter(
            ShopInventory.shop_id == shop_id,
            ShopInventory.product_id == product.id,
        )
        .first()
    )
    if inventory is None:
        inventory = ShopInventory(
            merchant_id=merchant_id,
            shop_id=shop_id,
            product_id=product.id,
        )
        db.add(inventory)
    inventory.stock = stock
    inventory.threshold = int(product.threshold or 0)


def record_shop_operation(entity_type: str, entity_id: int, db: Session) -> None:
    shop_id = get_current_shop_id(db)
    merchant_id = get_current_merchant(db)
    if shop_id is None or merchant_id is None:
        return
    db.add(
        ShopOperation(
            merchant_id=merchant_id,
            shop_id=shop_id,
            user_id=get_current_user_id(db),
            entity_type=entity_type,
            entity_id=entity_id,
        )
    )
