from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.payment_policy import OnlinePaymentStatus
from app.shared.events import DomainEvent, PaymentEvents
from app.shared.outbox import enqueue_domain_event


_ALLOWED_PAYMENT_TRANSITIONS = {
    OnlinePaymentStatus.UNPAID.value: {
        OnlinePaymentStatus.PAID.value,
        OnlinePaymentStatus.FAILED.value,
    },
    OnlinePaymentStatus.CASH_ON_DELIVERY.value: {
        OnlinePaymentStatus.PAID.value,
        OnlinePaymentStatus.FAILED.value,
    },
    OnlinePaymentStatus.MOBILE_MONEY_PENDING.value: {
        OnlinePaymentStatus.PAID.value,
        OnlinePaymentStatus.FAILED.value,
    },
    OnlinePaymentStatus.FAILED.value: {
        OnlinePaymentStatus.MOBILE_MONEY_PENDING.value,
    },
    OnlinePaymentStatus.PAID.value: set(),
}


def update_payment_status(
    *,
    merchant_id: int,
    order_id: int,
    status: str,
    db: Session,
) -> OnlineOrder:
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

    target = str(status).strip().lower()
    allowed = _ALLOWED_PAYMENT_TRANSITIONS.get(order.payment_status, set())
    if target not in allowed:
        raise ValueError(
            f"Transition de paiement invalide : {order.payment_status} -> {target}"
        )

    order.payment_status = target

    transaction = (
        db.query(BusinessTransaction)
        .filter(
            BusinessTransaction.id == order.transaction_id,
            BusinessTransaction.merchant_id == merchant_id,
        )
        .first()
    )
    if transaction is not None:
        transaction.payment_status = target

    if target == OnlinePaymentStatus.PAID.value:
        enqueue_domain_event(
            db,
            DomainEvent(
                event_type=PaymentEvents.RECEIVED,
                merchant_id=merchant_id,
                aggregate_type="online_order",
                aggregate_id=str(order.id),
                data={
                    "order_id": order.id,
                    "reference": order.reference,
                    "transaction_id": order.transaction_id,
                    "amount": order.total_amount,
                    "currency": order.currency,
                    "payment_method": order.payment_method,
                },
            ),
        )

    db.commit()
    db.refresh(order)
    return order
