from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal import cart_models as _cart_models  # noqa: F401
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.worker import (
    dispatch_notification_batch,
    recover_stale_processing,
)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _notification(*, event_id: str, status: str = "pending") -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        merchant_id=2,
        aggregate_type="online_order",
        aggregate_id="1",
        event_type="notification.requested",
        event_version=1,
        payload={
            "data": {
                "channel": "whatsapp",
                "recipient": "+22997000000",
                "message": "Commande prête",
            }
        },
        status=status,
        retry_count=0,
    )


def test_dispatch_notification_marks_published_and_captures_provider_id():
    db = _db()
    row = _notification(event_id="00000000-0000-0000-0000-000000000001")
    db.add(row)
    db.commit()

    calls = []

    def sender(to, body):
        calls.append((to, body))
        return {"messages": [{"id": "wamid.test-1"}]}

    result = dispatch_notification_batch(db=db, sender=sender)

    db.refresh(row)
    assert result == {"claimed": 1, "published": 1, "retried": 0, "failed": 0}
    assert calls == [("+22997000000", "Commande prête")]
    assert row.status == "published"
    assert row.provider_message_id == "wamid.test-1"
    assert row.published_at is not None
    assert row.processing_started_at is None
    db.close()


def test_dispatch_notification_retries_with_backoff():
    db = _db()
    row = _notification(event_id="00000000-0000-0000-0000-000000000002")
    db.add(row)
    db.commit()

    def sender(_to, _body):
        raise RuntimeError("provider unavailable")

    before = datetime.utcnow()
    result = dispatch_notification_batch(
        db=db,
        sender=sender,
        max_retries=3,
        base_backoff_seconds=30,
    )

    db.refresh(row)
    assert result == {"claimed": 1, "published": 0, "retried": 1, "failed": 0}
    assert row.status == "pending"
    assert row.retry_count == 1
    assert row.next_attempt_at is not None
    assert row.next_attempt_at >= before + timedelta(seconds=29)
    assert "provider unavailable" in row.last_error
    db.close()


def test_dispatch_notification_moves_to_failed_after_retry_limit():
    db = _db()
    row = _notification(event_id="00000000-0000-0000-0000-000000000003")
    row.retry_count = 2
    db.add(row)
    db.commit()

    def sender(_to, _body):
        raise ValueError("bad request")

    result = dispatch_notification_batch(db=db, sender=sender, max_retries=3)

    db.refresh(row)
    assert result == {"claimed": 1, "published": 0, "retried": 0, "failed": 1}
    assert row.status == "failed"
    assert row.retry_count == 3
    assert row.next_attempt_at is None
    db.close()


def test_dispatch_notification_ignores_non_notification_events():
    db = _db()
    row = OutboxEvent(
        event_id="00000000-0000-0000-0000-000000000004",
        merchant_id=2,
        aggregate_type="online_order",
        aggregate_id="1",
        event_type="commerce.order.completed",
        event_version=1,
        payload={"data": {"order_id": 1}},
        status="pending",
        retry_count=0,
    )
    db.add(row)
    db.commit()

    result = dispatch_notification_batch(
        db=db,
        sender=lambda _to, _body: {"messages": [{"id": "should-not-send"}]},
    )

    db.refresh(row)
    assert result == {"claimed": 0, "published": 0, "retried": 0, "failed": 0}
    assert row.status == "pending"
    db.close()


def test_recover_stale_processing_requeues_notification():
    db = _db()
    row = _notification(
        event_id="00000000-0000-0000-0000-000000000005",
        status="processing",
    )
    row.processing_started_at = datetime.utcnow() - timedelta(minutes=20)
    db.add(row)
    db.commit()

    recovered = recover_stale_processing(
        db=db,
        stale_minutes=10,
        max_retries=3,
    )

    db.refresh(row)
    assert recovered == 1
    assert row.status == "pending"
    assert row.retry_count == 1
    assert row.processing_started_at is None
    assert row.next_attempt_at is not None
    db.close()
