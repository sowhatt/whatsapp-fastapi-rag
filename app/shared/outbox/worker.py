from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.services.whatsapp_sender import send_whatsapp_text_message
from app.shared.events import NotificationEvents
from app.shared.tenancy.rls import apply_rls_bypass

from .model import OutboxEvent


Sender = Callable[[str, str], Any]


def _provider_message_id(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    first = messages[0]
    if not isinstance(first, dict):
        return None
    message_id = first.get("id")
    return str(message_id) if message_id else None


def recover_stale_processing(
    *,
    db: Session,
    stale_minutes: int = 10,
    max_retries: int = 3,
) -> int:
    apply_rls_bypass(db, enabled=True)
    now = datetime.utcnow()
    stale_before = now - timedelta(minutes=max(1, stale_minutes))
    rows = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type == NotificationEvents.REQUESTED,
            OutboxEvent.status == "processing",
            OutboxEvent.processing_started_at.isnot(None),
            OutboxEvent.processing_started_at <= stale_before,
        )
        .all()
    )

    for row in rows:
        row.retry_count += 1
        row.processing_started_at = None
        row.last_error = "Traitement interrompu ou expiré."
        if row.retry_count >= max_retries:
            row.status = "failed"
            row.next_attempt_at = None
        else:
            row.status = "pending"
            row.next_attempt_at = now

    if rows:
        db.commit()
    return len(rows)


def dispatch_notification_batch(
    *,
    db: Session,
    sender: Sender = send_whatsapp_text_message,
    limit: int = 20,
    max_retries: int = 3,
    base_backoff_seconds: int = 30,
) -> dict:
    apply_rls_bypass(db, enabled=True)
    now = datetime.utcnow()
    rows = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type == NotificationEvents.REQUESTED,
            OutboxEvent.status == "pending",
            or_(
                OutboxEvent.next_attempt_at.is_(None),
                OutboxEvent.next_attempt_at <= now,
            ),
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .with_for_update(skip_locked=True)
        .limit(max(1, min(limit, 100)))
        .all()
    )

    if not rows:
        return {"claimed": 0, "published": 0, "retried": 0, "failed": 0}

    claimed_ids = [row.id for row in rows]
    for row in rows:
        row.status = "processing"
        row.processing_started_at = now
    db.commit()

    published = 0
    retried = 0
    failed = 0

    for event_id in claimed_ids:
        apply_rls_bypass(db, enabled=True)
        row = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if row is None:
            db.rollback()
            continue
        try:
            data = (row.payload or {}).get("data") or {}
            channel = data.get("channel")
            recipient = data.get("recipient")
            message = data.get("message")
            if channel != "whatsapp":
                raise ValueError(f"Canal de notification non supporté : {channel!r}")
            if not recipient:
                raise ValueError("Destinataire WhatsApp manquant.")
            if not message:
                raise ValueError("Message WhatsApp manquant.")

            result = sender(str(recipient), str(message))
            row.status = "published"
            row.published_at = datetime.utcnow()
            row.processing_started_at = None
            row.next_attempt_at = None
            row.last_error = None
            row.provider_message_id = _provider_message_id(result)
            db.commit()
            published += 1
        except Exception as exc:
            db.rollback()
            apply_rls_bypass(db, enabled=True)
            current = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
            if current is None:
                continue

            current.retry_count += 1
            current.processing_started_at = None
            current.last_error = f"{type(exc).__name__}: {exc}"[:2000]

            if current.retry_count >= max_retries:
                current.status = "failed"
                current.next_attempt_at = None
                failed += 1
            else:
                current.status = "pending"
                delay = max(1, base_backoff_seconds) * (2 ** (current.retry_count - 1))
                current.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
                retried += 1
            db.commit()

    return {
        "claimed": len(rows),
        "published": published,
        "retried": retried,
        "failed": failed,
    }
