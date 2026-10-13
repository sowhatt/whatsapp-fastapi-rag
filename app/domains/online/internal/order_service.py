from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.public.stock import active_reservation_count, expire_reservations, release_reservations, reserve_stock
from app.domains.online.internal.order_models import OnlineOrder, OnlineOrderItem
from app.domains.online.internal.reservation_policy import order_reservation_minutes
from app.shared.events import CommerceEvents, DomainEvent
from app.shared.outbox import enqueue_domain_event
from app.models.product import Product


_ALLOWED_TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"preparing", "cancelled"},
    "preparing": {"ready", "cancelled"},
    "ready": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _reservation_status(order: OnlineOrder, *, db: Session) -> str:
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == order.merchant_id,
            StockReservation.source_type == "online_order",
            StockReservation.source_id == order.id,
        )
        .all()
    )
    if not rows:
        return "none"
    now = datetime.utcnow()
    if any(row.status == "active" and row.expires_at <= now for row in rows):
        return "expired"
    statuses = {row.status for row in rows}
    if "active" in statuses:
        return "active"
    if "expired" in statuses:
        return "expired"
    if "released" in statuses:
        return "released"
    if "consumed" in statuses:
        return "consumed"
    return sorted(statuses)[0]


def _order_payload(order: OnlineOrder, *, db: Session) -> dict:
    items = (
        db.query(OnlineOrderItem)
        .filter(
            OnlineOrderItem.merchant_id == order.merchant_id,
            OnlineOrderItem.order_id == order.id,
        )
        .order_by(OnlineOrderItem.id)
        .all()
    )
    return {
        "id": order.id,
        "reference": order.reference,
        "merchant_id": order.merchant_id,
        "store_id": order.store_id,
        "status": order.status,
        "payment_status": order.payment_status,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "delivery_mode": order.delivery_mode,
        "delivery_address": order.delivery_address,
        "notes": order.notes,
        "currency": order.currency,
        "subtotal": order.subtotal_amount,
        "delivery_amount": order.delivery_amount,
        "total": order.total_amount,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "reservation_status": _reservation_status(order, db=db),
        "items": [
            {
                "product_id": item.product_id,
                "name": item.product_name_snapshot,
                "unit": item.unit_snapshot,
                "quantity": item.quantity,
                "unit_price": item.unit_price_snapshot,
                "line_total": item.line_total,
            }
            for item in items
        ],
    }


def list_orders(
    *,
    merchant_id: int,
    db: Session,
    status: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    orders_query = db.query(OnlineOrder).filter(OnlineOrder.merchant_id == merchant_id)
    if status:
        orders_query = orders_query.filter(OnlineOrder.status == status)
    if query:
        search = f"%{query.strip()}%"
        orders_query = orders_query.filter(
            or_(
                OnlineOrder.reference.ilike(search),
                OnlineOrder.customer_name.ilike(search),
                OnlineOrder.customer_phone.ilike(search),
            )
        )
    orders = (
        orders_query.order_by(OnlineOrder.created_at.desc(), OnlineOrder.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_order_payload(order, db=db) for order in orders]


def get_order(*, merchant_id: int, order_id: int, db: Session) -> dict | None:
    order = (
        db.query(OnlineOrder)
        .filter(
            OnlineOrder.id == order_id,
            OnlineOrder.merchant_id == merchant_id,
        )
        .first()
    )
    if order is None:
        return None
    return _order_payload(order, db=db)


def update_order_status(
    *,
    merchant_id: int,
    order_id: int,
    status: str,
    db: Session,
) -> dict:
    order = (
        db.query(OnlineOrder)
        .filter(
            OnlineOrder.id == order_id,
            OnlineOrder.merchant_id == merchant_id,
        )
        .with_for_update()
        .first()
    )
    if order is None:
        raise ValueError("Commande Online introuvable.")

    target = status.strip().lower()
    allowed = _ALLOWED_TRANSITIONS.get(order.status)
    if allowed is None or target not in allowed:
        raise ValueError(
            f"Transition de commande invalide : {order.status} -> {target}"
        )

    if target == "confirmed":
        if active_reservation_count(
            merchant_id=merchant_id,
            source_type="online_order",
            source_id=order.id,
            db=db,
        ) == 0:
            raise ValueError("La réservation de stock a expiré. Revalidez la commande avant confirmation.")

    order.status = target

    if target == "cancelled":
        release_reservations(
            merchant_id=merchant_id,
            source_type="online_order",
            source_id=order.id,
            db=db,
        )
        enqueue_domain_event(
            db,
            DomainEvent(
                event_type=CommerceEvents.ORDER_CANCELLED,
                merchant_id=merchant_id,
                aggregate_type="online_order",
                aggregate_id=str(order.id),
                data={
                    "order_id": order.id,
                    "reference": order.reference,
                    "status": target,
                },
            ),
        )
    elif target == "confirmed":
        enqueue_domain_event(
            db,
            DomainEvent(
                event_type=CommerceEvents.ORDER_CONFIRMED,
                merchant_id=merchant_id,
                aggregate_type="online_order",
                aggregate_id=str(order.id),
                data={
                    "order_id": order.id,
                    "reference": order.reference,
                    "status": target,
                },
            ),
        )

    db.commit()
    db.refresh(order)
    return _order_payload(order, db=db)



def cleanup_expired_order_reservations(
    *,
    merchant_id: int,
    db: Session,
) -> int:
    count = expire_reservations(
        merchant_id=merchant_id,
        source_type="online_order",
        db=db,
    )
    db.commit()
    return count



def revalidate_order_reservations(
    *,
    merchant_id: int,
    order_id: int,
    db: Session,
) -> dict:
    order = (
        db.query(OnlineOrder)
        .filter(
            OnlineOrder.id == order_id,
            OnlineOrder.merchant_id == merchant_id,
        )
        .with_for_update()
        .first()
    )
    if order is None:
        raise ValueError("Commande Online introuvable.")
    if order.status != "pending":
        raise ValueError(
            "La revalidation du stock est réservée aux commandes en attente."
        )

    items = (
        db.query(OnlineOrderItem)
        .filter(
            OnlineOrderItem.merchant_id == merchant_id,
            OnlineOrderItem.order_id == order.id,
        )
        .order_by(OnlineOrderItem.product_id)
        .all()
    )
    if not items:
        raise ValueError("La commande ne contient aucun article.")

    active_count = active_reservation_count(
        merchant_id=merchant_id,
        source_type="online_order",
        source_id=order.id,
        db=db,
    )
    if active_count == len(items):
        return _order_payload(order, db=db)

    # Clean expired rows and release any partial active set before rebuilding
    # the complete reservation set deterministically.
    expire_reservations(
        merchant_id=merchant_id,
        source_type="online_order",
        source_id=order.id,
        db=db,
    )
    if active_count:
        release_reservations(
            merchant_id=merchant_id,
            source_type="online_order",
            source_id=order.id,
            db=db,
        )

    try:
        for item in items:
            product = (
                db.query(Product)
                .filter(
                    Product.id == item.product_id,
                    Product.merchant_id == merchant_id,
                )
                .first()
            )
            if product is None:
                raise ValueError(
                    f"Produit introuvable pour la commande : {item.product_name_snapshot}."
                )

            reserve_stock(
                merchant_id=merchant_id,
                product_id=item.product_id,
                quantity=item.quantity,
                source_type="online_order",
                source_id=order.id,
                db=db,
                minutes=order_reservation_minutes(),
            )

        db.commit()
        db.refresh(order)
        return _order_payload(order, db=db)
    except Exception:
        db.rollback()
        # Persist expiry cleanup even when the new reservation set cannot be rebuilt.
        expire_reservations(
            merchant_id=merchant_id,
            source_type="online_order",
            source_id=order.id,
            db=db,
        )
        db.commit()
        raise



def order_summary(*, merchant_id: int, db: Session) -> dict:
    status_rows = (
        db.query(OnlineOrder.status, func.count(OnlineOrder.id))
        .filter(OnlineOrder.merchant_id == merchant_id)
        .group_by(OnlineOrder.status)
        .all()
    )
    by_status = {status: int(count) for status, count in status_rows}

    gross_total = int(
        db.query(func.coalesce(func.sum(OnlineOrder.total_amount), 0))
        .filter(
            OnlineOrder.merchant_id == merchant_id,
            OnlineOrder.status != "cancelled",
        )
        .scalar()
        or 0
    )

    expired_reservations = int(
        db.query(func.count(StockReservation.id))
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == "online_order",
            StockReservation.status == "active",
            StockReservation.expires_at <= datetime.utcnow(),
        )
        .scalar()
        or 0
    )

    return {
        "merchant_id": merchant_id,
        "orders_total": sum(by_status.values()),
        "by_status": by_status,
        "gross_order_amount": gross_total,
        "expired_reservations": expired_reservations,
    }
