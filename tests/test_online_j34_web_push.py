from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal import transaction_model as _transaction_model  # noqa: F401
from app.domains.online.internal import cart_models as _cart_models  # noqa: F401
from app.domains.online.internal import models as _online_store_models  # noqa: F401
from app.domains.online.internal import order_models as _order_models  # noqa: F401
from app.models import merchant as _merchant_model  # noqa: F401
from app.models import product as _product_model  # noqa: F401
from app.routers.online_admin_web import online_admin_service_worker, online_admin_ui
from app.shared.notifications.model import OnlineNotification
from app.shared.notifications.push_model import WebPushSubscription
from app.shared.notifications.web_push import (
    dispatch_web_push_for_notification,
    web_push_enabled,
    web_push_public_key,
)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _enable_push_env(monkeypatch):
    monkeypatch.setenv("WEB_PUSH_VAPID_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("WEB_PUSH_VAPID_PRIVATE_KEY", "private-key")
    monkeypatch.setenv("WEB_PUSH_VAPID_SUBJECT", "mailto:test@example.com")


def test_web_push_config_requires_all_vapid_values(monkeypatch):
    monkeypatch.delenv("WEB_PUSH_VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("WEB_PUSH_VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("WEB_PUSH_VAPID_SUBJECT", raising=False)
    assert web_push_enabled() is False
    assert web_push_public_key() is None

    _enable_push_env(monkeypatch)
    assert web_push_enabled() is True
    assert web_push_public_key() == "public-key"


def test_dispatch_web_push_targets_active_merchant_subscription(monkeypatch):
    _enable_push_env(monkeypatch)
    db = _db()
    subscription = WebPushSubscription(
        merchant_id=2,
        endpoint="https://push.example.test/subscription/1",
        p256dh="p" * 32,
        auth="a" * 16,
        is_active=True,
    )
    notification = OnlineNotification(
        source_event_id="00000000-0000-0000-0000-000000000201",
        merchant_id=2,
        aggregate_type="online_order",
        aggregate_id="42",
        recipient_role="merchant",
        channel="in_app",
        title="Commande WO-42",
        body="Nouvelle commande.",
        action_url="/online-admin-ui#order-42",
        status="unread",
    )
    db.add_all([subscription, notification])
    db.commit()

    calls = []

    def sender(subscription_info, payload):
        calls.append((subscription_info, payload))
        return object()

    result = dispatch_web_push_for_notification(
        db=db,
        notification=notification,
        sender=sender,
    )

    assert result == {"attempted": 1, "sent": 1, "failed": 0}
    assert calls[0][0]["endpoint"] == subscription.endpoint
    assert calls[0][1]["url"] == "/online-admin-ui#order-42"
    assert calls[0][1]["title"] == "Commande WO-42"
    db.close()


def test_dispatch_web_push_skips_customer_handoff(monkeypatch):
    _enable_push_env(monkeypatch)
    db = _db()
    notification = OnlineNotification(
        source_event_id="00000000-0000-0000-0000-000000000202",
        merchant_id=2,
        aggregate_type="online_order",
        aggregate_id="42",
        recipient_role="customer",
        channel="whatsapp_handoff",
        title="Commande WO-42",
        body="Commande prête.",
        action_url="https://wa.me/22997000000",
        status="unread",
    )
    db.add(notification)
    db.commit()

    result = dispatch_web_push_for_notification(
        db=db,
        notification=notification,
        sender=lambda *_args: (_ for _ in ()).throw(AssertionError("must not send")),
    )

    assert result == {"attempted": 0, "sent": 0, "failed": 0}
    db.close()


def test_admin_ui_contains_push_opt_in_and_service_worker():
    html = online_admin_ui().body.decode()
    worker = online_admin_service_worker().body.decode()

    assert 'id="push-enable"' in html
    assert 'navigator.serviceWorker.register("/online-admin-sw.js")' in html
    assert 'Notification.requestPermission()' in html
    assert 'self.addEventListener("push"' in worker
    assert 'self.addEventListener("notificationclick"' in worker
