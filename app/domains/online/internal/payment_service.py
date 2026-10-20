from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.core.public.transactions import update_commerce_transaction
from app.domains.online.internal.mutation import tenant_mutation
from app.shared.tenancy.rls import apply_rls_context
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


@tenant_mutation
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
        .populate_existing()
        .with_for_update()
        .first()
    )
    if order is None:
        raise ValueError("Commande Online introuvable.")

    if order.status == "cancelled":
        raise ValueError("Le paiement d'une commande annulée ne peut plus être modifié.")

    target = str(status).strip().lower()
    if (
        target == OnlinePaymentStatus.MOBILE_MONEY_PENDING.value
        and order.payment_method != "mobile_money"
    ):
        raise ValueError("Le retry Mobile Money est réservé aux commandes Mobile Money.")

    allowed = _ALLOWED_PAYMENT_TRANSITIONS.get(order.payment_status, set())
    if target == order.payment_status:
        update_commerce_transaction(
            db=db, merchant_id=merchant_id, transaction_id=order.transaction_id,
            payment_status=target,
        )
        db.commit()
        apply_rls_context(db, merchant_id=merchant_id)
        db.refresh(order)
        return order
    if target not in allowed:
        raise ValueError(
            f"Transition de paiement invalide : {order.payment_status} -> {target}"
        )

    order.payment_status = target

    update_commerce_transaction(
        db=db, merchant_id=merchant_id, transaction_id=order.transaction_id,
        payment_status=target,
    )

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
    apply_rls_context(db, merchant_id=merchant_id)
    db.refresh(order)
    return order
