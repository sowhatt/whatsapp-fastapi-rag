from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.models.product import Product


DEFAULT_RESERVATION_MINUTES = 10


def reserved_quantity(
    *,
    merchant_id: int,
    product_id: int,
    db: Session,
    now: datetime | None = None,
    exclude_source_type: str | None = None,
    exclude_source_id: int | None = None,
) -> int:
    now = now or datetime.utcnow()

    query = db.query(
        func.coalesce(func.sum(StockReservation.quantity), 0)
    ).filter(
        StockReservation.merchant_id == merchant_id,
        StockReservation.product_id == product_id,
        or_(
            StockReservation.status == "consumed",
            and_(
                StockReservation.status == "active",
                StockReservation.expires_at > now,
            ),
        ),
    )

    if exclude_source_type is not None and exclude_source_id is not None:
        query = query.filter(
            ~(
                (StockReservation.source_type == exclude_source_type)
                & (StockReservation.source_id == exclude_source_id)
            )
        )

    return int(query.scalar() or 0)


def available_stock(
    *,
    product: Product,
    db: Session,
    now: datetime | None = None,
    exclude_source_type: str | None = None,
    exclude_source_id: int | None = None,
) -> int:
    if product.merchant_id is None:
        return int(product.stock or 0)

    # Phase A: consumed Online reservations remain unavailable to Online.
    # We deliberately do not mutate Product.stock because Shop is frozen.
    reserved = reserved_quantity(
        merchant_id=product.merchant_id,
        product_id=product.id,
        db=db,
        now=now,
        exclude_source_type=exclude_source_type,
        exclude_source_id=exclude_source_id,
    )
    return max(0, int(product.stock or 0) - reserved)


def reserve_stock(
    *,
    merchant_id: int,
    product_id: int,
    quantity: int,
    source_type: str,
    source_id: int,
    db: Session,
    minutes: int = DEFAULT_RESERVATION_MINUTES,
) -> StockReservation:
    if quantity <= 0:
        raise ValueError("La quantité réservée doit être positive.")

    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.merchant_id == merchant_id,
        )
        .with_for_update()
        .first()
    )
    if product is None:
        raise ValueError("Produit introuvable.")

    available = available_stock(product=product, db=db)
    if quantity > available:
        raise ValueError(
            f"Stock disponible insuffisant pour {product.name} : "
            f"{available} disponible(s), {quantity} demandé(s)."
        )

    reservation = StockReservation(
        merchant_id=merchant_id,
        product_id=product_id,
        quantity=quantity,
        source_type=source_type,
        source_id=source_id,
        status="active",
        expires_at=datetime.utcnow() + timedelta(minutes=minutes),
    )
    db.add(reservation)
    return reservation


def release_reservations(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
) -> int:
    now = datetime.utcnow()
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
        )
        .all()
    )
    for row in rows:
        row.status = "released"
        row.released_at = now
    return len(rows)


def consume_reservations(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
) -> int:
    now = datetime.utcnow()
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .all()
    )
    for row in rows:
        row.status = "consumed"
        row.consumed_at = now
    return len(rows)



def expire_reservations(
    *,
    db: Session,
    merchant_id: int | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
    now: datetime | None = None,
) -> int:
    now = now or datetime.utcnow()
    query = db.query(StockReservation).filter(
        StockReservation.status == "active",
        StockReservation.expires_at <= now,
    )
    if merchant_id is not None:
        query = query.filter(StockReservation.merchant_id == merchant_id)
    if source_type is not None:
        query = query.filter(StockReservation.source_type == source_type)
    if source_id is not None:
        query = query.filter(StockReservation.source_id == source_id)

    rows = query.all()
    for row in rows:
        row.status = "expired"
        row.released_at = now
    return len(rows)


def active_reservation_count(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
    now: datetime | None = None,
) -> int:
    now = now or datetime.utcnow()
    return int(
        db.query(func.count(StockReservation.id))
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .scalar()
        or 0
    )



def extend_reservations(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
    minutes: int,
) -> int:
    if minutes <= 0:
        raise ValueError("La durée de réservation doit être positive.")
    now = datetime.utcnow()
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .all()
    )
    new_expiry = now + timedelta(minutes=minutes)
    for row in rows:
        if row.expires_at < new_expiry:
            row.expires_at = new_expiry
    return len(rows)



def stock_position(
    *,
    product: Product,
    db: Session,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.utcnow()
    if product.merchant_id is None:
        physical = int(product.stock or 0)
        return {
            "stock_physical": physical,
            "stock_reserved_active": 0,
            "stock_consumed_online": 0,
            "stock_online_available": physical,
        }

    active_reserved = int(
        db.query(func.coalesce(func.sum(StockReservation.quantity), 0))
        .filter(
            StockReservation.merchant_id == product.merchant_id,
            StockReservation.product_id == product.id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .scalar()
        or 0
    )
    consumed_online = int(
        db.query(func.coalesce(func.sum(StockReservation.quantity), 0))
        .filter(
            StockReservation.merchant_id == product.merchant_id,
            StockReservation.product_id == product.id,
            StockReservation.status == "consumed",
            StockReservation.source_type == "online_order",
        )
        .scalar()
        or 0
    )
    physical = int(product.stock or 0)
    online_available = max(0, physical - active_reserved - consumed_online)

    return {
        "stock_physical": physical,
        "stock_reserved_active": active_reserved,
        "stock_consumed_online": consumed_online,
        "stock_online_available": online_available,
    }
