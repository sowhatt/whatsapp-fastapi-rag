from __future__ import annotations

import argparse
import json
import time

from sqlalchemy import func

from app.db.session import SessionLocal
from app.shared.events import NotificationEvents
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.worker import (
    dispatch_notification_batch,
    recover_stale_processing,
)


def _pending_count(db, *, merchant_id: int | None = None) -> int:
    query = db.query(func.count(OutboxEvent.id)).filter(
        OutboxEvent.event_type == NotificationEvents.REQUESTED,
        OutboxEvent.status == "pending",
    )
    if merchant_id is not None:
        query = query.filter(OutboxEvent.merchant_id == merchant_id)
    return int(query.scalar() or 0)


def _run_once(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        recovered = recover_stale_processing(
            db=db,
            stale_minutes=max(1, args.recover_stale_minutes),
            max_retries=max(1, args.max_retries),
        )
        pending_before = _pending_count(db, merchant_id=args.merchant_id)

        if not args.send:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "merchant_id": args.merchant_id,
                        "recovered": recovered,
                        "pending_notifications": pending_before,
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
        )
        result["mode"] = "send"
        result["merchant_id"] = args.merchant_id
        result["recovered"] = recovered
        result["pending_notifications_after"] = _pending_count(
            db,
            merchant_id=args.merchant_id,
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
