from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.online.internal.order_models import OnlineOrder
from app.shared.outbox.model import OutboxEvent


def pilot_readiness(
    *,
    merchant_id: int,
    db: Session,
    stale_minutes: int = 30,
) -> dict:
    now = datetime.utcnow()
    stale_before = now - timedelta(minutes=stale_minutes)

    expired_reservations = int(
        db.query(func.count(StockReservation.id))
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == "online_order",
            StockReservation.status == "active",
            StockReservation.expires_at <= now,
        )
        .scalar()
        or 0
    )

    pending_mobile_money = int(
        db.query(func.count(OnlineOrder.id))
        .filter(
            OnlineOrder.merchant_id == merchant_id,
            OnlineOrder.payment_status == "mobile_money_pending",
            OnlineOrder.status != "cancelled",
        )
        .scalar()
        or 0
    )

    failed_payments = int(
        db.query(func.count(OnlineOrder.id))
        .filter(
            OnlineOrder.merchant_id == merchant_id,
            OnlineOrder.payment_status == "failed",
            OnlineOrder.status != "cancelled",
        )
        .scalar()
        or 0
    )

    stale_pending_orders = int(
        db.query(func.count(OnlineOrder.id))
        .filter(
            OnlineOrder.merchant_id == merchant_id,
            OnlineOrder.status == "pending",
            OnlineOrder.created_at <= stale_before,
        )
        .scalar()
        or 0
    )

    pending_outbox = int(
        db.query(func.count(OutboxEvent.id))
        .filter(
            OutboxEvent.merchant_id == merchant_id,
            OutboxEvent.status == "pending",
        )
        .scalar()
        or 0
    )

    pending_notification_outbox = int(
        db.query(func.count(OutboxEvent.id))
        .filter(
            OutboxEvent.merchant_id == merchant_id,
            OutboxEvent.status == "pending",
            OutboxEvent.event_type == "notification.requested",
        )
        .scalar()
        or 0
    )

    pending_domain_outbox = max(
        0,
        pending_outbox - pending_notification_outbox,
    )

    failed_outbox = int(
        db.query(func.count(OutboxEvent.id))
        .filter(
            OutboxEvent.merchant_id == merchant_id,
            OutboxEvent.status == "failed",
        )
        .scalar()
        or 0
    )

    blockers = {
        "expired_reservations": expired_reservations,
        "failed_payments": failed_payments,
        "failed_outbox": failed_outbox,
    }
    warnings = {
        "pending_mobile_money": pending_mobile_money,
        "stale_pending_orders": stale_pending_orders,
        "pending_outbox": pending_outbox,
        "pending_notification_outbox": pending_notification_outbox,
        "pending_domain_outbox": pending_domain_outbox,
    }

    return {
        "merchant_id": merchant_id,
        "ready": not any(blockers.values()),
        "blockers": blockers,
        "warnings": warnings,
        "checked_at": now.isoformat(),
        "stale_after_minutes": stale_minutes,
    }
