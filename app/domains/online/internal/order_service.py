from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.public.stock import active_reservation_count, consume_reservations, expire_reservations, extend_reservations, release_reservations, reserve_stock
from app.domains.online.internal.order_models import OnlineOrder, OnlineOrderItem
from app.domains.online.internal.notification_service import enqueue_order_notifications
from app.domains.online.internal.reservation_policy import confirmed_order_reservation_minutes, order_reservation_minutes
from app.shared.events import CommerceEvents, DeliveryEvents, DomainEvent
from app.shared.outbox import enqueue_domain_event
from app.models.product import Product
from app.domains.core.public.transactions import TransactionStatus, update_commerce_transaction
from app.domains.online.internal.mutation import tenant_mutation
from app.shared.tenancy.rls import apply_rls_context


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
    # Historical expired rows are preserved for auditability. Once a rebuilt
    # reservation reaches a terminal state, that current state must win over
    # older expired rows from the same order.
    if "consumed" in statuses:
        return "consumed"
    if "released" in statuses:
        return "released"
    if "expired" in statuses:
        return "expired"
    return sorted(statuses)[0]


def _order_actions(order: OnlineOrder, *, reservation_status: str) -> dict:
    status = order.status

    actions = {
        "can_confirm": False,
        "can_mark_paid": order.payment_status != "paid" and order.status != "cancelled",
        "can_mark_payment_failed": order.payment_status in {"mobile_money_pending", "cash_on_delivery", "unpaid"} and order.status != "cancelled",
        "can_retry_mobile_money": order.payment_status == "failed" and order.payment_method == "mobile_money" and order.status != "cancelled",
        "can_prepare": False,
        "can_mark_ready": False,
        "can_complete": False,
        "can_cancel": False,
        "can_revalidate_stock": False,
        "needs_revalidation": False,
        "next_status": None,
        "recommended_action": None,
    }

    if status == "pending":
        actions["can_cancel"] = True
        if reservation_status == "active":
            actions["can_confirm"] = True
            actions["next_status"] = "confirmed"
            actions["recommended_action"] = "confirm"
        else:
            actions["can_revalidate_stock"] = True
            actions["needs_revalidation"] = True
            actions["recommended_action"] = "revalidate_stock"
    elif status == "confirmed":
        actions["can_prepare"] = True
        actions["can_cancel"] = True
        actions["next_status"] = "preparing"
        actions["recommended_action"] = "start_preparing"
    elif status == "preparing":
        actions["can_mark_ready"] = True
        actions["can_cancel"] = True
        actions["next_status"] = "ready"
        actions["recommended_action"] = "mark_ready"
    elif status == "ready":
        actions["can_complete"] = True
        actions["can_cancel"] = True
        actions["next_status"] = "completed"
        actions["recommended_action"] = "complete"

    return actions


def _order_priority(
    order: OnlineOrder,
    *,
    reservation_status: str,
    actions: dict,
) -> dict:
    if actions["needs_revalidation"]:
        return {"rank": 0, "key": "stock_expired", "label": "Stock à revalider"}
    if actions["can_confirm"]:
        return {"rank": 1, "key": "confirm", "label": "À confirmer"}
    if actions["can_prepare"]:
        return {"rank": 2, "key": "prepare", "label": "À préparer"}
    if actions["can_mark_ready"]:
        return {"rank": 3, "key": "ready", "label": "En préparation"}
    if actions["can_complete"]:
        return {"rank": 4, "key": "complete", "label": "Prête à terminer"}
    if order.status == "completed":
        return {"rank": 8, "key": "completed", "label": "Terminée"}
    if order.status == "cancelled":
        return {"rank": 9, "key": "cancelled", "label": "Annulée"}
    return {"rank": 7, "key": order.status, "label": order.status}


def _order_payload(order: OnlineOrder, *, db: Session) -> dict:
    reservation_status = _reservation_status(order, db=db)
    actions = _order_actions(order, reservation_status=reservation_status)
    priority = _order_priority(
        order,
        reservation_status=reservation_status,
        actions=actions,
    )
    age_minutes = max(
        0,
        int((datetime.utcnow() - order.created_at).total_seconds() // 60),
    )

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
        "payment_method": order.payment_method,
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
        "reservation_status": reservation_status,
        "actions": actions,
        "priority": priority,
        "age_minutes": age_minutes,
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
    payloads = [_order_payload(order, db=db) for order in orders]
    payloads.sort(
        key=lambda row: (
            row["priority"]["rank"],
            -row["age_minutes"],
            -row["id"],
        )
    )
    return payloads


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


@tenant_mutation
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
        .populate_existing()
        .with_for_update()
        .first()
    )
    if order is None:
        raise ValueError("Commande Online introuvable.")

    target = status.strip().lower()
    allowed = _ALLOWED_TRANSITIONS.get(order.status)
    replay = target == order.status
    if allowed is None or (not replay and target not in allowed):
        raise ValueError(
            f"Transition de commande invalide : {order.status} -> {target}"
        )

    if not replay and target in {"confirmed", "completed"}:
        if active_reservation_count(
            merchant_id=merchant_id,
            source_type="online_order",
            source_id=order.id,
            db=db,
        ) == 0:
            action = "confirmer" if target == "confirmed" else "terminer"
            raise ValueError(
                f"La réservation de stock a expiré. Revalidez avant de {action} la commande."
            )

    core_status = {
        "pending": TransactionStatus.PENDING,
        "confirmed": TransactionStatus.CONFIRMED,
        "preparing": TransactionStatus.CONFIRMED,
        "ready": TransactionStatus.CONFIRMED,
        "completed": TransactionStatus.COMPLETED,
        "cancelled": TransactionStatus.CANCELLED,
    }[target]
    update_commerce_transaction(
        db=db, merchant_id=merchant_id, transaction_id=order.transaction_id,
        status=core_status,
    )
    if replay:
        db.commit()
        apply_rls_context(db, merchant_id=merchant_id)
        return _order_payload(order, db=db)

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
        extend_reservations(
            merchant_id=merchant_id,
            source_type="online_order",
            source_id=order.id,
            db=db,
            minutes=confirmed_order_reservation_minutes(),
        )
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
        enqueue_order_notifications(
            order=order,
            stage="confirmed",
            db=db,
        )
        if order.delivery_mode == "delivery":
            enqueue_domain_event(
                db,
                DomainEvent(
                    event_type=DeliveryEvents.REQUESTED,
                    merchant_id=merchant_id,
                    aggregate_type="online_order",
                    aggregate_id=str(order.id),
                    data={
                        "order_id": order.id,
                        "reference": order.reference,
                        "delivery_address": order.delivery_address,
                        "customer_phone": order.customer_phone,
                        "currency": order.currency,
                    },
                ),
            )
    elif target == "ready":
        enqueue_order_notifications(
            order=order,
            stage="ready",
            db=db,
        )
    elif target == "completed":
        consume_reservations(
            merchant_id=merchant_id,
            source_type="online_order",
            source_id=order.id,
            db=db,
        )
        enqueue_domain_event(
            db,
            DomainEvent(
                event_type=CommerceEvents.ORDER_COMPLETED,
                merchant_id=merchant_id,
                aggregate_type="online_order",
                aggregate_id=str(order.id),
                data={
                    "order_id": order.id,
                    "reference": order.reference,
                    "payment_status": order.payment_status,
                    "delivery_mode": order.delivery_mode,
                },
            ),
        )
        enqueue_order_notifications(
            order=order,
            stage="completed",
            db=db,
        )

    db.commit()
    apply_rls_context(db, merchant_id=merchant_id)
    db.refresh(order)
    return _order_payload(order, db=db)



@tenant_mutation
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



@tenant_mutation
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
        .populate_existing()
        .with_for_update()
        .first()
    )
    if order is None:
        raise ValueError("Commande Online introuvable.")
    if order.status in {"completed", "cancelled"}:
        raise ValueError(
            "La revalidation du stock n'est plus autorisée pour cette commande."
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
        apply_rls_context(db, merchant_id=merchant_id)
        db.refresh(order)
        return _order_payload(order, db=db)
    except Exception:
        db.rollback()
        apply_rls_context(db, merchant_id=merchant_id)
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

    pending_orders = (
        db.query(OnlineOrder)
        .filter(
            OnlineOrder.merchant_id == merchant_id,
            OnlineOrder.status == "pending",
        )
        .all()
    )

    needs_revalidation = 0
    can_confirm = 0
    for order in pending_orders:
        reservation_status = _reservation_status(order, db=db)
        actions = _order_actions(order, reservation_status=reservation_status)
        if actions["needs_revalidation"]:
            needs_revalidation += 1
        if actions["can_confirm"]:
            can_confirm += 1

    attention = {
        "can_confirm": can_confirm,
        "needs_revalidation": needs_revalidation,
        "to_prepare": by_status.get("confirmed", 0),
        "to_mark_ready": by_status.get("preparing", 0),
        "to_complete": by_status.get("ready", 0),
    }
    attention["total"] = sum(attention.values())

    payment_rows = (
        db.query(OnlineOrder.payment_status, func.count(OnlineOrder.id))
        .filter(OnlineOrder.merchant_id == merchant_id)
        .group_by(OnlineOrder.payment_status)
        .all()
    )
    payment_by_status = {
        status: int(count)
        for status, count in payment_rows
    }
    paid_amount = int(
        db.query(func.coalesce(func.sum(OnlineOrder.total_amount), 0))
        .filter(
            OnlineOrder.merchant_id == merchant_id,
            OnlineOrder.payment_status == "paid",
            OnlineOrder.status != "cancelled",
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
        "attention": attention,
        "payment_by_status": payment_by_status,
        "paid_amount": paid_amount,
    }
