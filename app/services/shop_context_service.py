from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.db.tenant import get_current_merchant
from app.models.product import Product
from app.models.shop_inventory import ShopInventory
from app.models.shop_operation import ShopOperation


def get_current_shop_id(db: Session) -> int | None:
    return db.info.get("pwa_shop_id") or db.info.get("resolved_shop_id")


def get_current_user_id(db: Session) -> int | None:
    return db.info.get("pwa_user_id") or db.info.get("resolved_user_id")


def _inventory_row(product: Product, db: Session, *, lock: bool = False):
    shop_id = get_current_shop_id(db)
    if shop_id is None:
        return None
    query = db.query(ShopInventory).filter(
        ShopInventory.shop_id == shop_id,
        ShopInventory.product_id == product.id,
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def get_effective_stock(product: Product, db: Session) -> int:
    shop_id = get_current_shop_id(db)
    if shop_id is None:
        return int(product.stock or 0)
    inventory = _inventory_row(product, db)
    return int(inventory.stock if inventory is not None else 0)


def adjust_stock(product: Product, quantity_delta: int, db: Session) -> int:
    shop_id = get_current_shop_id(db)
    merchant_id = get_current_merchant(db) or getattr(product, "merchant_id", None)
    if shop_id is None:
        product.stock = int(product.stock or 0) + quantity_delta
        return product.stock
    if merchant_id is None:
        raise ValueError("merchant_id requis pour un stock de boutique")

    inventory = _inventory_row(product, db, lock=True)
    if inventory is None:
        inventory = ShopInventory(
            merchant_id=merchant_id,
            shop_id=shop_id,
            product_id=product.id,
            stock=0,
            threshold=int(product.threshold or 0),
        )
        db.add(inventory)

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

    inventory = _inventory_row(product, db)
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


@event.listens_for(Session, "loaded_as_persistent")
def _overlay_shop_stock(session: Session, instance) -> None:
    """Expose le stock de la boutique comme `Product.stock` dans la requête courante."""
    if not isinstance(instance, Product):
        return
    if get_current_shop_id(session) is None:
        return

    legacy_stock = int(instance.stock or 0)
    inventory = _inventory_row(instance, session)
    shop_stock = int(inventory.stock if inventory is not None else 0)

    instance.__dict__["_whatzabi_legacy_stock"] = legacy_stock
    instance.__dict__["_whatzabi_shop_stock_snapshot"] = shop_stock
    set_committed_value(instance, "stock", shop_stock)


@event.listens_for(Session, "before_flush")
def _redirect_product_stock_changes_to_shop(session: Session, flush_context, instances) -> None:
    """Legacy services may still modify Product.stock; redirect that delta to the selected shop."""
    shop_id = get_current_shop_id(session)
    merchant_id = get_current_merchant(session)
    if shop_id is None or merchant_id is None:
        return

    for product in list(session.dirty):
        if not isinstance(product, Product):
            continue
        if "_whatzabi_legacy_stock" not in product.__dict__:
            continue

        previous_shop_stock = int(product.__dict__.get("_whatzabi_shop_stock_snapshot", 0))
        requested_shop_stock = int(product.stock or 0)
        legacy_stock = int(product.__dict__.get("_whatzabi_legacy_stock", 0))

        if requested_shop_stock != previous_shop_stock:
            inventory = _inventory_row(product, session, lock=True)
            if inventory is None:
                inventory = ShopInventory(
                    merchant_id=merchant_id,
                    shop_id=shop_id,
                    product_id=product.id,
                    stock=previous_shop_stock,
                    threshold=int(product.threshold or 0),
                )
                session.add(inventory)
            if requested_shop_stock < 0:
                raise ValueError("stock insuffisant")
            inventory.stock = requested_shop_stock
            product.__dict__["_whatzabi_shop_stock_snapshot"] = requested_shop_stock

        set_committed_value(product, "stock", legacy_stock)
