from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal import transaction_model as _transaction_model  # noqa: F401
from app.domains.online.internal import cart_models as _cart_models  # noqa: F401
from app.domains.online.internal import models as _online_store_models  # noqa: F401
from app.domains.online.internal import order_models as _order_models  # noqa: F401
from app.models import merchant as _merchant_model  # noqa: F401
from app.models import product as _product_model  # noqa: F401
from app.domains.online.internal.notification_templates import (
    absolute_tracking_url,
    public_base_url,
)
from app.shared.notifications.model import OnlineNotification
from app.shared.notifications.worker import (
    materialize_notification_batch,
    whatsapp_handoff_url,
)
from app.shared.outbox.model import OutboxEvent


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _event(*, event_id: str, role: str, channel: str, recipient: str | None):
    return OutboxEvent(
        event_id=event_id,
        merchant_id=2,
        aggregate_type="online_order",
        aggregate_id="1",
        event_type="notification.requested",
        event_version=1,
        payload={
            "data": {
                "channel": channel,
                "recipient_role": role,
                "recipient": recipient,
                "title": "Commande WO-TEST",
                "message": "Votre commande est prête.",
            }
        },
        status="pending",
        retry_count=0,
    )


def test_whatsapp_handoff_url_is_provider_free():
    url = whatsapp_handoff_url(
        recipient="+22997000000",
        message="Commande prête",
    )
    assert url.startswith("https://wa.me/22997000000?text=")
    assert "Commande%20pr%C3%AAte" in url


def test_legacy_customer_whatsapp_event_becomes_handoff():
    db = _db()
    row = _event(
        event_id="00000000-0000-0000-0000-000000000101",
        role="customer",
        channel="whatsapp",
        recipient="+22997000000",
    )
    db.add(row)
    db.commit()

    result = materialize_notification_batch(db=db, merchant_id=2)

    db.refresh(row)
    notification = db.query(OnlineNotification).one()
    assert result == {"claimed": 1, "published": 1, "retried": 0, "failed": 0}
    assert row.status == "published"
    assert notification.channel == "whatsapp_handoff"
    assert notification.recipient_role == "customer"
    assert notification.action_url.startswith("https://wa.me/22997000000?text=")
    assert notification.source_event_id == row.event_id
    db.close()


def test_legacy_merchant_whatsapp_event_becomes_in_app_even_with_non_phone_recipient():
    db = _db()
    row = _event(
        event_id="00000000-0000-0000-0000-000000000102",
        role="merchant",
        channel="whatsapp",
        recipient="testing",
    )
    db.add(row)
    db.commit()

    result = materialize_notification_batch(db=db, merchant_id=2)

    db.refresh(row)
    notification = db.query(OnlineNotification).one()
    assert result == {"claimed": 1, "published": 1, "retried": 0, "failed": 0}
    assert row.status == "published"
    assert notification.channel == "in_app"
    assert notification.recipient_role == "merchant"
    assert notification.action_url is None
    db.close()


def test_materialization_is_idempotent_by_source_event():
    db = _db()
    row = _event(
        event_id="00000000-0000-0000-0000-000000000103",
        role="merchant",
        channel="in_app",
        recipient=None,
    )
    db.add(row)
    db.commit()

    first = materialize_notification_batch(db=db, merchant_id=2)
    row.status = "pending"
    row.published_at = None
    db.commit()
    second = materialize_notification_batch(db=db, merchant_id=2)

    assert first["published"] == 1
    assert second["published"] == 1
    assert db.query(OnlineNotification).count() == 1
    db.close()



def test_public_base_url_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("ONLINE_PUBLIC_BASE_URL", "https://online.example.com/")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "ignored.example.com")

    assert public_base_url() == "https://online.example.com"
    assert absolute_tracking_url(path="/shop/demo/order/WO-1") == (
        "https://online.example.com/shop/demo/order/WO-1"
    )


def test_public_base_url_falls_back_to_railway_domain(monkeypatch):
    monkeypatch.delenv("ONLINE_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv(
        "RAILWAY_PUBLIC_DOMAIN",
        "whatzabi-online-staging-staging.up.railway.app",
    )

    assert public_base_url() == (
        "https://whatzabi-online-staging-staging.up.railway.app"
    )
    assert absolute_tracking_url(path="/shop/demo/order/WO-1") == (
        "https://whatzabi-online-staging-staging.up.railway.app"
        "/shop/demo/order/WO-1"
    )


def test_absolute_tracking_url_keeps_relative_path_without_public_domain(monkeypatch):
    monkeypatch.delenv("ONLINE_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)

    assert absolute_tracking_url(path="/shop/demo/order/WO-1") == (
        "/shop/demo/order/WO-1"
    )
