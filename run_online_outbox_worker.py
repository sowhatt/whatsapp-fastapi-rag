from __future__ import annotations

import argparse
import json

from sqlalchemy import func

from app.db.session import SessionLocal
from app.shared.events import NotificationEvents
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.worker import (
    dispatch_notification_batch,
    recover_stale_processing,
)


def _pending_count(db) -> int:
    return int(
        db.query(func.count(OutboxEvent.id))
        .filter(
            OutboxEvent.event_type == NotificationEvents.REQUESTED,
            OutboxEvent.status == "pending",
        )
        .scalar()
        or 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch Whatzabi Online notification outbox events.",
    )
    parser.add_argument("--send", action="store_true", help="Actually send WhatsApp notifications.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--recover-stale-minutes", type=int, default=10)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        recovered = recover_stale_processing(
            db=db,
            stale_minutes=max(1, args.recover_stale_minutes),
            max_retries=max(1, args.max_retries),
        )
        pending_before = _pending_count(db)

        if not args.send:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "recovered": recovered,
                        "pending_notifications": pending_before,
                        "message": "Use --send to dispatch WhatsApp notifications.",
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        result = dispatch_notification_batch(
            db=db,
            limit=max(1, min(args.limit, 100)),
            max_retries=max(1, args.max_retries),
        )
        result["recovered"] = recovered
        result["pending_notifications_after"] = _pending_count(db)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["failed"] == 0 else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
