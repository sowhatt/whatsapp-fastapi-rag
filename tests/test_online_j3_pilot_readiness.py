from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal import cart_models as _cart_models  # noqa: F401
from app.domains.online.internal.pilot_readiness import pilot_readiness
from app.models.merchant import Merchant
from app.shared.outbox.model import OutboxEvent


def test_readiness_splits_notification_and_domain_outbox():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    merchant = Merchant(whatsapp_number="pilot-j3", shop_name="Pilot J3")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    db.add_all(
        [
            OutboxEvent(
                event_id="00000000-0000-0000-0000-000000000101",
                merchant_id=merchant.id,
                aggregate_type="online_order",
                aggregate_id="1",
                event_type="notification.requested",
                event_version=1,
                payload={"data": {}},
                status="pending",
                retry_count=0,
            ),
            OutboxEvent(
                event_id="00000000-0000-0000-0000-000000000102",
                merchant_id=merchant.id,
                aggregate_type="online_order",
                aggregate_id="1",
                event_type="commerce.order.completed",
                event_version=1,
                payload={"data": {}},
                status="pending",
                retry_count=0,
            ),
        ]
    )
    db.commit()

    result = pilot_readiness(merchant_id=merchant.id, db=db)

    assert result["warnings"]["pending_outbox"] == 2
    assert result["warnings"]["pending_notification_outbox"] == 1
    assert result["warnings"]["pending_domain_outbox"] == 1
    db.close()
