from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.domains.online.foundation import require_business_type, require_capability

from app.domains.online.internal.catalog_models import OnlineProductImage, OnlineProductPublication

from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.online.internal.cart_models import OnlineCart, OnlineCartItem
from app.domains.online.internal.order_models import OnlineOrder, OnlineOrderItem
from app.domains.online.internal.notification_service import enqueue_order_notifications
from app.domains.online.internal.payment_policy import initial_payment_status, normalize_payment_method
from app.domains.online.internal.reservation_policy import order_reservation_minutes
from app.domains.online.internal.store_service import get_public_store, get_store_capabilities
from app.domains.online.public.order_tracking import order_next_step, order_status_label, payment_status_label
from app.models.product import Product
from app.shared.events import CommerceEvents, DomainEvent
from app.shared.outbox import enqueue_domain_event
from app.shared.tenancy.rls import apply_rls_context
from app.domains.core.public.stock import available_stock, reserve_stock



def _checkout_result(order: OnlineOrder, *, replay: bool = False) -> dict[str, Any]:
    return {
        "id": order.id,
        "reference": order.reference,
        "status": order.status,
        "status_label": order_status_label(order.status),
        "next_step": order_next_step(order.status),
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "payment_status_label": payment_status_label(order.payment_status),
        "currency": order.currency,
        "subtotal": order.subtotal_amount,
        "delivery_amount": order.delivery_amount,
        "total": order.total_amount,
        "delivery_mode": order.delivery_mode,
        "stock_reserved": order.status not in {"cancelled", "completed"},
        "reservation_minutes": order_reservation_minutes(),
        "idempotent_replay": replay,
    }


def checkout_cart(
    *,
    slug: str,
    token: str,
    customer_name: str,
    customer_phone: str,
    delivery_mode: str,
    delivery_address: str | None,
    notes: str | None,
    payment_method: str = "cash_on_delivery",
    db: Session,
) -> dict[str, Any] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None
    require_business_type(store.business_type, "commerce")
    require_capability(get_store_capabilities(store), "checkout")

    # Online binds PostgreSQL RLS explicitly for its own transaction.
    # Whatzabi Shop session/tenant behavior remains untouched.
    apply_rls_context(db, merchant_id=store.merchant_id, bypass=False)

    if delivery_mode not in {"pickup", "delivery"}:
        raise ValueError("Mode de remise invalide.")
    resolved_payment_method = normalize_payment_method(payment_method)
    resolved_payment_status = initial_payment_status(resolved_payment_method).value
    capabilities = get_store_capabilities(store)
    require_capability(capabilities, delivery_mode)
    if delivery_mode == "delivery" and not (delivery_address or "").strip():
        raise ValueError("L'adresse de livraison est obligatoire.")

    cart = (
        db.query(OnlineCart)
        .filter(
            OnlineCart.token == token,
            OnlineCart.store_id == store.id,
            OnlineCart.merchant_id == store.merchant_id,
        )
        .with_for_update()
        .first()
    )
    if cart is None:
        return None

    if cart.status == "converted":
        existing = (
            db.query(OnlineOrder)
            .filter(
                OnlineOrder.cart_id == cart.id,
                OnlineOrder.merchant_id == store.merchant_id,
            )
            .first()
        )
        if existing is not None:
            return _checkout_result(existing, replay=True)
        raise ValueError("Panier converti sans commande associée.")

    if cart.status != "active":
        raise ValueError("Ce panier n'est plus actif.")

    if cart.expires_at <= datetime.utcnow():
        raise ValueError("Ce panier a expiré.")

    cart_items = (
        db.query(OnlineCartItem)
        .filter(
            OnlineCartItem.cart_id == cart.id,
            OnlineCartItem.merchant_id == store.merchant_id,
        )
        .order_by(OnlineCartItem.id)
        .all()
    )
    if not cart_items:
        raise ValueError("Le panier est vide.")

    resolved_items = []
    subtotal = 0

    for item in cart_items:
        row = (
            db.query(Product, OnlineProductPublication)
            .join(OnlineProductPublication, OnlineProductPublication.product_id == Product.id)
            .filter(
                Product.id == item.product_id,
                Product.merchant_id == store.merchant_id,
                OnlineProductPublication.merchant_id == store.merchant_id,
                OnlineProductPublication.is_published.is_(True),
                OnlineProductPublication.is_active.is_(True),
            )
            .first()
        )
        if row is None:
            raise ValueError("Un produit du panier n'est plus disponible.")

        product, publication = row
        if not publication.show_price:
            raise ValueError(f"{product.name} n'est plus commandable en ligne.")
        current_available = available_stock(product=product, db=db)
        if item.quantity > current_available:
            raise ValueError(
                f"Stock disponible insuffisant pour {product.name} : "
                f"{current_available} disponible(s)."
            )

        unit_price = product.price
        line_total = unit_price * item.quantity
        subtotal += line_total
        resolved_items.append((product, item.quantity, unit_price, line_total))

    # Acquire product locks in a deterministic order across concurrent checkouts.
    resolved_items.sort(key=lambda row: row[0].id)

    delivery_amount = 0
    total = subtotal + delivery_amount

    transaction = BusinessTransaction(
        merchant_id=store.merchant_id,
        shop_id=None,
        kind="commerce",
        status="pending",
        currency=store.currency,
        subtotal_amount=subtotal,
        tax_amount=0,
        fee_amount=delivery_amount,
        discount_amount=0,
        total_amount=total,
        payment_status=resolved_payment_status,
    )
    db.add(transaction)
    db.flush()

    order = OnlineOrder(
        merchant_id=store.merchant_id,
        store_id=store.id,
        transaction_id=transaction.id,
        cart_id=cart.id,
        status="pending",
        customer_name=customer_name.strip()[:150],
        customer_phone=customer_phone.strip()[:40],
        delivery_mode=delivery_mode,
        delivery_address=(delivery_address.strip()[:500] if delivery_address else None),
        notes=(notes.strip()[:500] if notes else None),
        currency=store.currency,
        subtotal_amount=subtotal,
        delivery_amount=delivery_amount,
        total_amount=total,
        payment_method=resolved_payment_method.value,
        payment_status=resolved_payment_status,
    )
    db.add(order)
    db.flush()

    for product, quantity, unit_price, line_total in resolved_items:
        db.add(
            OnlineOrderItem(
                merchant_id=store.merchant_id,
                order_id=order.id,
                product_id=product.id,
                product_name_snapshot=product.name,
                unit_snapshot=product.unit,
                quantity=quantity,
                unit_price_snapshot=unit_price,
                line_total=line_total,
            )
        )
        reserve_stock(
            merchant_id=store.merchant_id,
            product_id=product.id,
            quantity=quantity,
            source_type="online_order",
            source_id=order.id,
            db=db,
            minutes=order_reservation_minutes(),
        )

    cart.status = "converted"

    enqueue_domain_event(
        db,
        DomainEvent(
            event_type=CommerceEvents.ORDER_CREATED,
            merchant_id=store.merchant_id,
            aggregate_type="online_order",
            aggregate_id=str(order.id),
            data={
                "order_id": order.id,
                "reference": order.reference,
                "transaction_id": transaction.id,
                "store_id": store.id,
                "total_amount": total,
                "currency": store.currency,
                "delivery_mode": delivery_mode,
                "payment_method": resolved_payment_method.value,
                "payment_status": resolved_payment_status,
            },
        ),
    )

    enqueue_order_notifications(
        order=order,
        stage="created",
        db=db,
    )

    db.commit()
    db.refresh(order)

    return _checkout_result(order)


def read_public_order(
    *,
    slug: str,
    reference: str,
    phone: str,
    db: Session,
) -> dict[str, Any] | None:
    store = get_public_store(slug=slug, db=db)
    if store is None:
        return None
    require_business_type(store.business_type, "commerce")

    order = (
        db.query(OnlineOrder)
        .filter(
            OnlineOrder.store_id == store.id,
            OnlineOrder.merchant_id == store.merchant_id,
            OnlineOrder.reference == reference.upper(),
            OnlineOrder.customer_phone == phone.strip()[:40],
        )
        .first()
    )
    if order is None:
        return None

    return {
        "reference": order.reference,
        "status": order.status,
        "status_label": order_status_label(order.status),
        "next_step": order_next_step(order.status),
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "payment_status_label": payment_status_label(order.payment_status),
        "currency": order.currency,
        "subtotal": order.subtotal_amount,
        "delivery_amount": order.delivery_amount,
        "total": order.total_amount,
        "delivery_mode": order.delivery_mode,
        "created_at": order.created_at.isoformat(),
    }
