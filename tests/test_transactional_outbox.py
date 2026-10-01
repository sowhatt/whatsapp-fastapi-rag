from app.shared.events import CommerceEvents, DomainEvent
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.service import enqueue_domain_event


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)


def test_enqueue_domain_event_does_not_commit():
    db = FakeSession()
    event = DomainEvent(
        event_type=CommerceEvents.ORDER_CREATED,
        merchant_id=42,
        aggregate_type="commerce_order",
        aggregate_id="123",
        data={"total_amount": 10500},
    )

    row = enqueue_domain_event(db, event)

    assert db.added == [row]
    assert isinstance(row, OutboxEvent)
    assert row.event_id == str(event.event_id)
    assert row.merchant_id == 42
    assert row.status == "pending"
    assert row.payload["event_type"] == "commerce.order.created"
    assert not hasattr(db, "commit")


def test_outbox_has_unique_event_id():
    assert OutboxEvent.__table__.c.event_id.unique is True
