from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.events import NotificationEvents
from app.shared.outbox.model import OutboxEvent
from app.shared.tenancy.rls import apply_rls_bypass

from .model import OnlineNotification


def whatsapp_handoff_url(*, recipient: str, message: str) -> str:
    digits = "".join(ch for ch in str(recipient) if ch.isdigit())
    if len(digits) < 8:
        raise ValueError("Destinataire WhatsApp invalide pour handoff.")
    return f"https://wa.me/{digits}?text={quote(str(message), safe='')}"


def _materialized_payload(row: OutboxEvent) -> dict:
    data = (row.payload or {}).get("data") or {}
    channel = str(data.get("channel") or "").strip()
    recipient_role = str(data.get("recipient_role") or "").strip()

    # Backward compatibility for J3 events already queued before the
    # PWA-first decision: merchant messages become in-app notifications,
    # customer messages become explicit WhatsApp handoffs.
    if channel == "whatsapp":
        channel = "in_app" if recipient_role == "merchant" else "whatsapp_handoff"
    message = str(data.get("message") or "").strip()
    title = str(data.get("title") or "").strip()

    if channel not in {"in_app", "whatsapp_handoff"}:
        raise ValueError(f"Canal de notification non supporté : {channel!r}")
    if not recipient_role:
        raise ValueError("recipient_role manquant.")
    if not message:
        raise ValueError("Message de notification manquant.")

    action_url = data.get("action_url")
    if channel == "whatsapp_handoff":
        recipient = data.get("recipient")
        if not recipient:
            raise ValueError("Destinataire WhatsApp manquant pour handoff.")
        action_url = whatsapp_handoff_url(
            recipient=str(recipient),
            message=message,
        )

    if not title:
        title = "Whatzabi"

    return {
        "source_event_id": row.event_id,
        "merchant_id": row.merchant_id,
        "aggregate_type": row.aggregate_type,
        "aggregate_id": row.aggregate_id,
        "recipient_role": recipient_role,
        "channel": channel,
        "title": title,
        "body": message,
        "action_url": str(action_url) if action_url else None,
    }


def materialize_notification_batch(
    *,
    db: Session,
    limit: int = 20,
    merchant_id: int | None = None,
    event_id: int | None = None,
) -> dict:
    """Materialize PWA/handoff notifications without calling Meta or another provider."""
    apply_rls_bypass(db, enabled=True)
    now = datetime.utcnow()

    query = db.query(OutboxEvent).filter(
        OutboxEvent.event_type == NotificationEvents.REQUESTED,
        OutboxEvent.status == "pending",
        or_(
            OutboxEvent.next_attempt_at.is_(None),
            OutboxEvent.next_attempt_at <= now,
        ),
    )
    if merchant_id is not None:
        query = query.filter(OutboxEvent.merchant_id == merchant_id)
    if event_id is not None:
        query = query.filter(OutboxEvent.id == event_id)

    rows = (
        query.order_by(OutboxEvent.created_at, OutboxEvent.id)
        .with_for_update(skip_locked=True)
        .limit(max(1, min(limit, 100)))
        .all()
    )

    published = 0
    failed = 0

    for row in rows:
        try:
            payload = _materialized_payload(row)
            existing = (
                db.query(OnlineNotification)
                .filter(OnlineNotification.source_event_id == row.event_id)
                .first()
            )
            if existing is None:
                db.add(OnlineNotification(**payload))
            row.status = "published"
            row.published_at = datetime.utcnow()
            row.processing_started_at = None
            row.next_attempt_at = None
            row.last_error = None
            row.provider_message_id = None
            db.commit()
            published += 1
        except (ValueError, IntegrityError) as exc:
            db.rollback()
            apply_rls_bypass(db, enabled=True)
            current = db.query(OutboxEvent).filter(OutboxEvent.id == row.id).first()
            if current is not None:
                current.status = "failed"
                current.processing_started_at = None
                current.next_attempt_at = None
                current.retry_count += 1
                current.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                db.commit()
            failed += 1

    return {
        "claimed": len(rows),
        "published": published,
        "retried": 0,
        "failed": failed,
    }
