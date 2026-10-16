from __future__ import annotations

import argparse
import json
import os
import time

from sqlalchemy import func

from app.db.session import SessionLocal
from app.shared.events import NotificationEvents
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.worker import (
    dispatch_notification_batch,
    recover_stale_processing,
)
from app.shared.tenancy.rls import apply_rls_bypass


def _mask_recipient(value: str | None) -> str | None:
    if not value:
        return value
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:3]}***{text[-3:]}"


def _pending_query(db, *, merchant_id: int | None = None, event_id: int | None = None):
    apply_rls_bypass(db, enabled=True)
    query = db.query(OutboxEvent).filter(
        OutboxEvent.event_type == NotificationEvents.REQUESTED,
        OutboxEvent.status == "pending",
    )
    if merchant_id is not None:
        query = query.filter(OutboxEvent.merchant_id == merchant_id)
    if event_id is not None:
        query = query.filter(OutboxEvent.id == event_id)
    return query


def _pending_count(db, *, merchant_id: int | None = None, event_id: int | None = None) -> int:
    query = _pending_query(
        db,
        merchant_id=merchant_id,
        event_id=event_id,
    ).with_entities(func.count(OutboxEvent.id))
    return int(query.scalar() or 0)


def _pending_preview(
    db,
    *,
    merchant_id: int | None = None,
    event_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    rows = (
        _pending_query(
            db,
            merchant_id=merchant_id,
            event_id=event_id,
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(max(1, min(limit, 100)))
        .all()
    )
    result = []
    for row in rows:
        data = (row.payload or {}).get("data") or {}
        result.append(
            {
                "id": row.id,
                "merchant_id": row.merchant_id,
                "aggregate_id": row.aggregate_id,
                "recipient_role": data.get("recipient_role"),
                "recipient": _mask_recipient(data.get("recipient")),
                "template": data.get("template"),
                "retry_count": row.retry_count,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return result


def _validate_send_environment() -> None:
    missing = [
        name
        for name in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID")
        if not (os.getenv(name) or "").strip()
    ]
    if missing:
        raise SystemExit(
            "Missing WhatsApp worker environment variables: " + ", ".join(missing)
        )


def _run_once(args: argparse.Namespace) -> int:
    if args.send:
        _validate_send_environment()

    db = SessionLocal()
    try:
        recovered = recover_stale_processing(
            db=db,
            stale_minutes=max(1, args.recover_stale_minutes),
            max_retries=max(1, args.max_retries),
        )
        pending_before = _pending_count(
            db,
            merchant_id=args.merchant_id,
            event_id=args.event_id,
        )

        if not args.send:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "merchant_id": args.merchant_id,
                        "event_id": args.event_id,
                        "recovered": recovered,
                        "pending_notifications": pending_before,
                        "preview": _pending_preview(
                            db,
                            merchant_id=args.merchant_id,
                            event_id=args.event_id,
                            limit=args.limit,
                        ),
                        "message": "Use --send to dispatch WhatsApp notifications.",
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return 0

        result = dispatch_notification_batch(
            db=db,
            limit=max(1, min(args.limit, 100)),
            max_retries=max(1, args.max_retries),
            merchant_id=args.merchant_id,
            event_id=args.event_id,
        )
        result["mode"] = "send"
        result["merchant_id"] = args.merchant_id
        result["event_id"] = args.event_id
        result["recovered"] = recovered
        result["pending_notifications_after"] = _pending_count(
            db,
            merchant_id=args.merchant_id,
            event_id=args.event_id,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result["failed"] == 0 else 2
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch Whatzabi Online notification outbox events.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send WhatsApp notifications. Without this flag the command is a dry-run.",
    )
    parser.add_argument("--merchant-id", type=int, default=None)
    parser.add_argument("--event-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--recover-stale-minutes", type=int, default=10)
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously. Intended for the dedicated Railway worker service.",
    )
    parser.add_argument("--interval-seconds", type=int, default=10)
    args = parser.parse_args()

    if args.event_id is not None and args.loop:
        parser.error("--event-id cannot be combined with --loop.")

    if not args.loop:
        return _run_once(args)

    if not args.send:
        parser.error("--loop requires --send to avoid a useless permanent dry-run process.")

    exit_code = 0
    try:
        while True:
            exit_code = max(exit_code, _run_once(args))
            time.sleep(max(1, args.interval_seconds))
    except KeyboardInterrupt:
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
