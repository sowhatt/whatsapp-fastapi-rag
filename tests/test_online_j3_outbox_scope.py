from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal import cart_models as _cart_models  # noqa: F401
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.worker import dispatch_notification_batch


def test_dispatch_scoped_to_one_merchant():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    common = {
        "aggregate_type": "online_order",
        "aggregate_id": "1",
        "event_type": "notification.requested",
        "event_version": 1,
        "payload": {
            "data": {
                "channel": "whatsapp",
                "recipient": "+22997000000",
                "message": "Commande prête",
            }
        },
        "status": "pending",
        "retry_count": 0,
    }

    row_a = OutboxEvent(
        event_id="00000000-0000-0000-0000-000000000006",
        merchant_id=2,
        **common,
    )
    row_b = OutboxEvent(
        event_id="00000000-0000-0000-0000-000000000007",
        merchant_id=3,
        **common,
    )
    db.add_all([row_a, row_b])
    db.commit()

    sent = []

    def sender(to, body):
        sent.append((to, body))
        return {"messages": [{"id": "wamid.scoped"}]}

    result = dispatch_notification_batch(
        db=db,
        sender=sender,
        merchant_id=2,
        limit=10,
    )

    db.refresh(row_a)
    db.refresh(row_b)
    assert result == {"claimed": 1, "published": 1, "retried": 0, "failed": 0}
    assert row_a.status == "published"
    assert row_b.status == "pending"
    assert len(sent) == 1
    db.close()
