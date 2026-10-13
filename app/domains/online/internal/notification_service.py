from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.online.internal.models import OnlineStore
from app.domains.online.internal.notification_templates import render_order_notification, tracking_path
from app.domains.online.internal.order_models import OnlineOrder
from app.models.merchant import Merchant
from app.shared.events import DomainEvent, NotificationEvents
from app.shared.outbox import enqueue_domain_event


_STAGE_TEMPLATES = {
    "created": {
        "customer": "online_order_created_customer",
        "merchant": "online_order_created_merchant",
    },
    "confirmed": {
        "customer": "online_order_confirmed_customer",
        "merchant": "online_order_confirmed_merchant",
    },
    "ready": {
        "customer": "online_order_ready_customer",
        "merchant": "online_order_ready_merchant",
    },
    "completed": {
        "customer": "online_order_completed_customer",
        "merchant": "online_order_completed_merchant",
    },
}


def _context(order: OnlineOrder, *, stage: str) -> dict:
    return {
        "stage": stage,
        "order_id": order.id,
        "reference": order.reference,
        "status": order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "delivery_mode": order.delivery_mode,
        "total_amount": order.total_amount,
        "currency": order.currency,
    }


def enqueue_order_notifications(
    *,
    order: OnlineOrder,
    stage: str,
    db: Session,
) -> int:
    templates = _STAGE_TEMPLATES.get(stage)
    if templates is None:
        raise ValueError(f"Étape de notification Online inconnue : {stage}")

    merchant = (
        db.query(Merchant)
        .filter(Merchant.id == order.merchant_id)
        .first()
    )
    if merchant is None:
        raise ValueError("Commerçant introuvable pour notification Online.")

    store = (
        db.query(OnlineStore)
        .filter(OnlineStore.id == order.store_id)
        .first()
    )
    store_name = (
        (store.display_name if store else None)
        or merchant.shop_name
        or "Whatzabi"
    )
    customer_tracking_path = (
        tracking_path(
            store_slug=store.slug,
            reference=order.reference,
            phone=order.customer_phone,
        )
        if store is not None
        else None
    )

    messages = (
        (
            "customer",
            order.customer_phone,
            templates["customer"],
        ),
        (
            "merchant",
            merchant.whatsapp_number,
            templates["merchant"],
        ),
    )

    count = 0
    for recipient_role, recipient, template in messages:
        if not recipient:
            continue
        message = render_order_notification(
            stage=stage,
            recipient_role=recipient_role,
            reference=order.reference,
            customer_name=order.customer_name,
            total_amount=order.total_amount,
            currency=order.currency,
            delivery_mode=order.delivery_mode,
            payment_status=order.payment_status,
            store_name=store_name,
            tracking_url_path=(
                customer_tracking_path
                if recipient_role == "customer"
                else None
            ),
        )
        enqueue_domain_event(
            db,
            DomainEvent(
                event_type=NotificationEvents.REQUESTED,
                merchant_id=order.merchant_id,
                aggregate_type="online_order",
                aggregate_id=str(order.id),
                data={
                    "channel": "whatsapp",
                    "recipient_role": recipient_role,
                    "recipient": recipient,
                    "template": template,
                    "message": message,
                    "tracking_path": (
                        customer_tracking_path
                        if recipient_role == "customer"
                        else None
                    ),
                    "context": _context(order, stage=stage),
                },
            ),
        )
        count += 1

    return count
