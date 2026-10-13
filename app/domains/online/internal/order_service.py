from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.core.public.stock import active_reservation_count, expire_reservations, release_reservations
from app.domains.online.internal.order_models import OnlineOrder, OnlineOrderItem
from app.shared.events import CommerceEvents, DomainEvent
from app.shared.outbox import enqueue_domain_event


_ALLOWED_TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"preparing", "cancelled"},
    "preparing": {"ready", "cancelled"},
    "ready": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


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
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    query = db.query(OnlineOrder).filter(OnlineOrder.merchant_id == merchant_id)
    if status:
        query = query.filter(OnlineOrder.status == status)
    orders = (
        query.order_by(OnlineOrder.created_at.desc(), OnlineOrder.id.desc())
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

    expire_reservations(
        merchant_id=merchant_id,
        source_type="online_order",
        source_id=order.id,
        db=db,
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
