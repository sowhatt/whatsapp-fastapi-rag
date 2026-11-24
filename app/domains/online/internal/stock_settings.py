"""Réglages de stock Online du commerçant : lecture, validation, écriture.

Garde-fous :
- la boutique de préparation doit appartenir au commerçant et être active ;
- tampon, seuil et quantité du jour sont bornés (jamais négatifs) ;
- le mode de stock d'un produit ne change pas tant qu'une commande en cours le réserve,
  pour ne jamais perdre la sortie de stock d'une commande déjà acceptée.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.online.internal.catalog_models import OnlineProductPublication
from app.domains.online.internal.models import OnlineStore
from app.domains.online.internal.mutation import tenant_mutation
from app.domains.online.internal.stock_policy import (
    DEFAULT_LOW_STOCK_THRESHOLD,
    STOCK_MODES,
)
from app.domains.online.internal.store_service import get_or_create_store
from app.models.product import Product
from app.models.shop import Shop

MAX_BUFFER = 10_000
MAX_THRESHOLD = 1_000
MAX_DAILY_QUANTITY = 100_000

_UNSET = object()


def _active_shops(merchant_id: int, db: Session) -> list[Shop]:
    return (
        db.query(Shop)
        .filter(Shop.merchant_id == merchant_id, Shop.is_active.is_(True))
        .order_by(Shop.id)
        .all()
    )


def _fulfilment_state(store: OnlineStore | None, shops: list[Shop]) -> str:
    if not shops:
        return "none"  # stock du produit (commerçant sans Shop)
    ids = {s.id for s in shops}
    if store is not None and store.fulfilment_shop_id is not None:
        return "explicit" if store.fulfilment_shop_id in ids else "invalid"
    return "single" if len(shops) == 1 else "ambiguous"


def read_stock_settings(*, merchant_id: int, db: Session) -> dict:
    store = db.query(OnlineStore).filter(OnlineStore.merchant_id == merchant_id).first()
    shops = _active_shops(merchant_id, db)
    pubs = {
        p.product_id: p
        for p in db.query(OnlineProductPublication).filter(
            OnlineProductPublication.merchant_id == merchant_id
        )
    }
    products = []
    for product in (
        db.query(Product).filter(Product.merchant_id == merchant_id).order_by(Product.name)
    ):
        pub = pubs.get(product.id)
        products.append({
            "product_id": product.id,
            "name": product.name,
            "is_published": bool(pub and pub.is_published),
            "stock_mode": (pub.stock_mode if pub and pub.stock_mode in STOCK_MODES else "tracked"),
            "daily_quantity": pub.daily_quantity if pub else None,
            "stock_buffer_override": pub.stock_buffer_override if pub else None,
        })
    return {
        "fulfilment_shop_id": store.fulfilment_shop_id if store else None,
        "fulfilment_state": _fulfilment_state(store, shops),
        "stock_buffer": int(store.stock_buffer or 0) if store else 0,
        "low_stock_threshold": (
            int(store.low_stock_threshold)
            if store is not None and store.low_stock_threshold is not None
            else DEFAULT_LOW_STOCK_THRESHOLD
        ),
        "shops": [{"id": s.id, "name": s.name, "code": s.code} for s in shops],
        "products": products,
    }


def _bounded(value, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} doit être un nombre entier.")
    if value < 0 or value > maximum:
        raise ValueError(f"{name} doit être compris entre 0 et {maximum}.")
    return value


@tenant_mutation
def update_store_stock_settings(
    *, merchant_id: int, db: Session,
    fulfilment_shop_id=_UNSET, stock_buffer=_UNSET, low_stock_threshold=_UNSET,
) -> dict:
    store = get_or_create_store(merchant_id=merchant_id, db=db)
    if fulfilment_shop_id is not _UNSET:
        if fulfilment_shop_id is None:
            store.fulfilment_shop_id = None
        else:
            if not any(s.id == fulfilment_shop_id for s in _active_shops(merchant_id, db)):
                raise ValueError("Cette boutique n'existe pas ou n'est pas active pour ce commerçant.")
            store.fulfilment_shop_id = int(fulfilment_shop_id)
    if stock_buffer is not _UNSET:
        store.stock_buffer = _bounded(stock_buffer, name="Le tampon", maximum=MAX_BUFFER)
    if low_stock_threshold is not _UNSET:
        store.low_stock_threshold = _bounded(
            low_stock_threshold, name="Le seuil « dernières unités »", maximum=MAX_THRESHOLD
        )
    db.commit()
    return read_stock_settings(merchant_id=merchant_id, db=db)


def _has_open_reservation(merchant_id: int, product_id: int, db: Session) -> bool:
    now = datetime.utcnow()
    rows = db.query(StockReservation).filter(
        StockReservation.merchant_id == merchant_id,
        StockReservation.product_id == product_id,
        StockReservation.status.in_(["active", "consumed"]),
    )
    return any(r.status == "consumed" or r.expires_at > now for r in rows)


@tenant_mutation
def update_product_stock_settings(
    *, merchant_id: int, product_id: int, db: Session,
    stock_mode=_UNSET, daily_quantity=_UNSET, stock_buffer_override=_UNSET,
) -> dict:
    pub = (
        db.query(OnlineProductPublication)
        .filter(
            OnlineProductPublication.merchant_id == merchant_id,
            OnlineProductPublication.product_id == product_id,
        )
        .with_for_update()
        .first()
    )
    if pub is None:
        raise ValueError("Publiez d'abord ce produit en ligne avant de régler son stock.")

    new_mode = pub.stock_mode if stock_mode is _UNSET else stock_mode
    if new_mode not in STOCK_MODES:
        raise ValueError("Mode de stock invalide : suivi, quantité du jour ou sur commande.")
    if new_mode != pub.stock_mode and _has_open_reservation(merchant_id, product_id, db):
        raise ValueError(
            "Des commandes en cours utilisent ce produit : terminez-les ou annulez-les "
            "avant de changer son mode de stock."
        )

    new_daily = pub.daily_quantity if daily_quantity is _UNSET else daily_quantity
    if new_daily is not None:
        new_daily = _bounded(new_daily, name="La quantité du jour", maximum=MAX_DAILY_QUANTITY)
    if new_mode == "daily" and new_daily is None:
        raise ValueError("Indiquez la quantité du jour pour ce produit.")

    if stock_buffer_override is not _UNSET and stock_buffer_override is not None:
        _bounded(stock_buffer_override, name="Le tampon du produit", maximum=MAX_BUFFER)

    pub.stock_mode = new_mode
    pub.daily_quantity = new_daily
    if stock_buffer_override is not _UNSET:
        pub.stock_buffer_override = stock_buffer_override
    db.commit()
    return next(p for p in read_stock_settings(merchant_id=merchant_id, db=db)["products"]
                if p["product_id"] == product_id)
