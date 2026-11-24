"""Politique de stock Online : lit le stock de la boutique du Shop, sans l'écrire.

Résolution de la boutique de préparation (jamais de somme de plusieurs boutiques) :
1. `OnlineStore.fulfilment_shop_id` si défini (doit appartenir au commerçant et être active) ;
2. sinon, l'unique boutique active du commerçant ;
3. sinon, aucune boutique : stock historique `Product.stock` ;
4. plusieurs boutiques sans choix explicite, ou boutique invalide : rien n'est vendable
   (fail-closed) tant que le commerçant n'a pas désigné sa boutique de préparation.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.core.public.stock import StockPolicy, available_stock
from app.domains.online.internal.catalog_models import OnlineProductPublication
from app.domains.online.internal.models import OnlineStore
from app.models.product import Product
from app.models.shop import Shop

DEFAULT_LOW_STOCK_THRESHOLD = 2
STOCK_MODES = ("tracked", "daily", "unlimited")


def _store_for(merchant_id: int, db: Session) -> OnlineStore | None:
    return db.query(OnlineStore).filter(OnlineStore.merchant_id == merchant_id).first()


def resolve_stock_policy(*, merchant_id: int, product_id: int | None, db: Session) -> StockPolicy:
    store = _store_for(merchant_id, db)
    mode, daily_quantity = "tracked", None
    if product_id is not None:
        row = (
            db.query(OnlineProductPublication.stock_mode, OnlineProductPublication.daily_quantity)
            .filter(
                OnlineProductPublication.merchant_id == merchant_id,
                OnlineProductPublication.product_id == product_id,
            )
            .first()
        )
        if row is not None and row[0] in STOCK_MODES:
            mode, daily_quantity = row[0], row[1]
    if mode != "tracked":
        # Ces modes ne lisent ni n'écrivent le stock du Shop : aucune boutique à résoudre.
        buffer = int(store.stock_buffer or 0) if (store is not None and mode == "daily") else 0
        return StockPolicy(shop_id=None, buffer=max(0, buffer), mode=mode,
                           daily_quantity=daily_quantity)
    shops = (
        db.query(Shop.id)
        .filter(Shop.merchant_id == merchant_id, Shop.is_active.is_(True))
        .all()
    )
    active_ids = {row[0] for row in shops}

    shop_id: int | None
    fail_closed = False
    if store is not None and store.fulfilment_shop_id is not None:
        if store.fulfilment_shop_id in active_ids:
            shop_id = store.fulfilment_shop_id
        else:
            shop_id, fail_closed = None, True
    elif len(active_ids) == 1:
        shop_id = next(iter(active_ids))
    elif len(active_ids) == 0:
        shop_id = None
    else:
        shop_id, fail_closed = None, True

    buffer = int(store.stock_buffer or 0) if store is not None else 0
    if product_id is not None:
        override = (
            db.query(OnlineProductPublication.stock_buffer_override)
            .filter(
                OnlineProductPublication.merchant_id == merchant_id,
                OnlineProductPublication.product_id == product_id,
            )
            .scalar()
        )
        if override is not None:
            buffer = int(override)
    return StockPolicy(shop_id=shop_id, buffer=max(0, buffer), fail_closed=fail_closed)


def online_available_stock(*, product: Product, db: Session, **kwargs) -> int:
    policy = resolve_stock_policy(merchant_id=product.merchant_id, product_id=product.id, db=db) \
        if product.merchant_id is not None else None
    return available_stock(product=product, db=db, policy=policy, **kwargs)


def low_stock_threshold(*, merchant_id: int, db: Session) -> int:
    store = _store_for(merchant_id, db)
    if store is None or store.low_stock_threshold is None:
        return DEFAULT_LOW_STOCK_THRESHOLD
    return max(0, int(store.low_stock_threshold))


def availability(*, available: int, threshold: int) -> dict:
    """État d'affichage : en stock, dernières unités (sur confirmation) ou rupture."""
    if available <= 0:
        state = "out_of_stock"
    elif threshold > 0 and available <= threshold:
        state = "low_stock"
    else:
        state = "in_stock"
    return {"availability": state, "requires_confirmation": state == "low_stock"}
