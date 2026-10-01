from sqlalchemy.orm import Session

from app.shared.events import DomainEvent

from .model import OutboxEvent


def enqueue_domain_event(db: Session, event: DomainEvent) -> OutboxEvent:
    """Persist an event in the caller's current SQL transaction.

    This function intentionally does not commit. The aggregate change and
    outbox row therefore succeed or roll back together.
    """
    row = OutboxEvent(
        event_id=str(event.event_id),
        merchant_id=event.merchant_id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        event_version=event.event_version,
        payload=event.to_payload(),
        status="pending",
        retry_count=0,
    )
    db.add(row)
    return row
