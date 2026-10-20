import argparse
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event

from app import online_outbox_worker as worker
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.worker import recover_stale_processing
from tests.test_online_j42_core_consistency import db  # noqa: F401


def rows(db):
    result = []
    for merchant, status, event_type in [
        (1, "processing", "notification.requested"),
        (1, "processing", "notification.requested"),
        (2, "processing", "notification.requested"),
        (1, "processing", "commerce.order.completed"),
        (1, "pending", "notification.requested"),
    ]:
        row = OutboxEvent(
            event_id=str(uuid4()), merchant_id=merchant, aggregate_type="online_order",
            aggregate_id="1", event_type=event_type, event_version=1, payload={"data": {}},
            status=status, retry_count=0,
            processing_started_at=datetime.utcnow() - timedelta(hours=1) if status == "processing" else None,
        )
        db.add(row)
        result.append(row)
    db.commit()
    return result


def snapshot(db):
    return [
        tuple(getattr(row, column.name) for column in OutboxEvent.__table__.columns)
        for row in db.query(OutboxEvent).order_by(OutboxEvent.id)
    ]


def args(**changes):
    return argparse.Namespace(**{
        "send": False, "merchant_id": 1, "event_id": None,
        "recover_stale_minutes": 10, "max_retries": 3, "limit": 20,
        **changes,
    })


def test_dry_run_is_strictly_read_only_even_with_stale_processing(db, monkeypatch, capsys):
    rows(db)
    before = snapshot(db)
    statements = []
    event.listen(db.bind, "before_cursor_execute",
                 lambda conn, cursor, statement, parameters, context, many: statements.append(statement))
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)

    def forbidden(*a, **kw):
        pytest.fail("Dry-run must not commit, recover, or materialize")

    monkeypatch.setattr(db, "commit", forbidden)
    monkeypatch.setattr(worker, "recover_stale_processing", forbidden)
    monkeypatch.setattr(worker, "materialize_notification_batch", forbidden)
    assert worker._run_once(args()) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["recovered"] == 0
    assert result["pending_notifications"] == 1
    assert all(row["merchant_id"] == 1 for row in result["preview"])
    assert snapshot(db) == before
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)


@pytest.mark.parametrize("scope", ["merchant", "event", "both", "mismatch"])
def test_recovery_preserves_merchant_and_event_filters(db, scope):
    seeded = rows(db)
    selected = seeded[0].id
    recovered = recover_stale_processing(
        db=db, merchant_id=(2 if scope == "mismatch" else 1) if scope != "event" else None,
        event_id=selected if scope != "merchant" else None,
    )
    expected = 0 if scope == "mismatch" else 2 if scope == "merchant" else 1
    assert recovered == expected
    for index, row in enumerate(seeded):
        db.refresh(row)
        changed = scope != "mismatch" and (index == 0 or (scope == "merchant" and index == 1))
        assert row.retry_count == int(changed)
        if changed:
            assert row.status == "pending"
        elif index < 4:
            assert row.status == "processing"


def test_send_forwards_identical_filters_to_recovery_and_materialization(db, monkeypatch, capsys):
    seeded = rows(db)
    selected = seeded[0].id
    calls = []
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)

    def recover(**kwargs):
        calls.append(("recover", kwargs["merchant_id"], kwargs["event_id"]))
        return 0

    def materialize(**kwargs):
        calls.append(("materialize", kwargs["merchant_id"], kwargs["event_id"]))
        return {"failed": 0}

    monkeypatch.setattr(worker, "recover_stale_processing", recover)
    monkeypatch.setattr(worker, "materialize_notification_batch", materialize)
    assert worker._run_once(args(send=True, event_id=selected)) == 0
    assert calls == [("recover", 1, selected), ("materialize", 1, selected)]
