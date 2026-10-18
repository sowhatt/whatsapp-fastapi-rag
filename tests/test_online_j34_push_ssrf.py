"""No external DNS/HTTP and no real credentials: all keys are ephemeral fixtures."""
import base64
import io
import socket
import ssl
from unittest.mock import Mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
import requests
from requests.adapters import BaseAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from urllib3.response import HTTPResponse

from app.db.base import Base
from app.db.session import get_db
from app.domains.core.internal import transaction_model as _transactions  # noqa: F401
from app.domains.online.internal import cart_models as _carts  # noqa: F401
from app.domains.online.internal import models as _stores  # noqa: F401
from app.domains.online.internal import order_models as _orders  # noqa: F401
from app.routers.online_admin import router
from app.security import require_admin_token
from app.shared.notifications import push_endpoint, web_push, worker
from app.shared.notifications.model import OnlineNotification
from app.shared.notifications.push_model import WebPushSubscription
from app.shared.outbox.model import OutboxEvent


ENDPOINT = "https://fcm.googleapis.com/push/test-token"


def dns_answers(*addresses):
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM,
         socket.IPPROTO_TCP, "", (ip, 443))
        for ip in addresses
    ]


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setenv("WEB_PUSH_ALLOWED_HOST_SUFFIXES", "googleapis.com, push.example.test")
    monkeypatch.setenv("WEB_PUSH_VAPID_PUBLIC_KEY", "test-public")
    monkeypatch.setenv("WEB_PUSH_VAPID_PRIVATE_KEY", "test-private")
    monkeypatch.setenv("WEB_PUSH_VAPID_SUBJECT", "mailto:test@example.test")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", Mock(return_value=dns_answers("8.8.8.8")))
    # A regression must fail locally instead of touching a real network.
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("Unexpected network")))


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(require_admin_token)])
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as value:
        yield value


def subscribe(client, endpoint=ENDPOINT, authenticated=True):
    return client.post(
        "/online-admin/merchants/2/push-subscriptions",
        headers={"X-Admin-Token": "test-admin"} if authenticated else {},
        json={"endpoint": endpoint, "keys": {"p256dh": "p" * 32, "auth": "a" * 16}},
    )


@pytest.mark.parametrize("endpoint", [
    ENDPOINT, "https://googleapis.com/push/token",
    "https://sub.fcm.googleapis.com:443/push/token", "https://FCM.GOOGLEAPIS.COM/push/token",
])
def test_https_allowed_host_and_subdomains(endpoint):
    assert push_endpoint.validate_push_endpoint(endpoint).addresses == ("8.8.8.8",)


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/token", "https:///token", "https://",
    "https://localhost/token", "https://localhost./token", "https://a.localhost/token",
    "https://service.local/token", "https://service.internal/token",
    "https://home.arpa/token", "https://service.home.arpa/token",
    "https://127.0.0.1/token", "https://[::1]/token",
    "https://10.0.0.1/token", "https://172.16.0.1/token", "https://192.168.0.1/token",
    "https://169.254.169.254/token", "https://2130706433/token", "https://127.1/token",
    "https://user:password@fcm.googleapis.com/token", "https://@fcm.googleapis.com/token",
    "https://fcm.googleapis.com:8443/token", "https://fcm.googleapis.com:/token",
    "https://fcm.googleapis.com:99999/token", "https://fcm.googleapis.com:bad/token",
    "https://evilgoogleapis.com/token", "https://googleapis.com.evil.test/token",
    "https://fcm.googleapis.com./token", "https://fcm.googleapis.com/token#fragment",
    "https://fcm.googleapis.com\\@localhost/token", "https://fcm.googleapis.com/\nsecret",
    None, 123, {}, "not-a-url",
])
def test_api_rejects_invalid_url_without_record_or_sensitive_error(client, db, endpoint):
    response = subscribe(client, endpoint)
    assert response.status_code == 422
    assert response.json() == {"detail": "Souscription Web Push invalide."}
    assert db.query(WebPushSubscription).count() == 0
    push_endpoint.socket.getaddrinfo.assert_not_called()


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.1.1",
    "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1",
    "192.0.2.1", "198.51.100.1", "203.0.113.1", "198.18.0.1",
    "::1", "::", "fc00::1", "fe80::1", "ff02::1", "2001:db8::1", "3fff::1",
    "::ffff:127.0.0.1", "64:ff9b::a00:1", "2002:0a00:0001::1", "2001::1",
])
def test_dns_non_public_addresses_rejected_at_api(client, db, monkeypatch, address):
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", Mock(return_value=dns_answers(address)))
    assert subscribe(client).status_code == 422
    assert db.query(WebPushSubscription).count() == 0


@pytest.mark.parametrize("addresses", [
    ("8.8.8.8", "10.0.0.1"), ("10.0.0.1", "8.8.8.8"), ("8.8.8.8", "::1"), (),
])
def test_mixed_or_empty_dns_rejected(monkeypatch, addresses):
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", Mock(return_value=dns_answers(*addresses)))
    with pytest.raises(push_endpoint.InvalidPushEndpoint):
        push_endpoint.validate_push_endpoint(ENDPOINT)


def test_public_ipv6_accepted(monkeypatch):
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", Mock(return_value=dns_answers("2606:4700:4700::1111")))
    assert push_endpoint.validate_push_endpoint(ENDPOINT).addresses == ("2606:4700:4700::1111",)


def test_dns_error_is_generic(client, db, monkeypatch):
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", Mock(side_effect=socket.gaierror("sensitive details")))
    response = subscribe(client)
    assert response.status_code == 422
    assert response.json() == {"detail": "Souscription Web Push invalide."}
    assert db.query(WebPushSubscription).count() == 0


@pytest.mark.parametrize("value", ["", "*", "com", "googleapis.com,", ".googleapis.com", "127.0.0.1", "home.arpa"])
@pytest.mark.parametrize("environment", ["staging", "production", "development"])
def test_allowlist_fails_closed(monkeypatch, value, environment):
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("WEB_PUSH_ALLOWED_HOST_SUFFIXES", value)
    assert web_push.web_push_enabled() is False
    with pytest.raises(push_endpoint.InvalidPushEndpoint):
        push_endpoint.validate_push_endpoint(ENDPOINT)


def test_api_auth_and_valid_subscription(client, db):
    assert subscribe(client, authenticated=False).status_code == 403
    assert db.query(WebPushSubscription).count() == 0
    assert subscribe(client).status_code == 201
    assert subscribe(client).status_code == 201
    row = db.query(WebPushSubscription).one()
    assert row.merchant_id == 2 and row.is_active


@pytest.mark.parametrize("payload", [
    {"endpoint": "https://user:sensitive@localhost/token"},
    {"endpoint": ENDPOINT, "keys": {"p256dh": "bad", "auth": "sensitive"}},
    ["sensitive"], None,
])
def test_invalid_request_body_never_echoes_input(client, db, payload):
    response = client.post("/online-admin/merchants/2/push-subscriptions",
                           headers={"X-Admin-Token": "test-admin"}, json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Souscription Web Push invalide."}
    assert db.query(WebPushSubscription).count() == 0


def notification(db):
    row = OnlineNotification(
        source_event_id="00000000-0000-0000-0000-000000000701",
        merchant_id=2, aggregate_type="online_order", aggregate_id="42",
        recipient_role="merchant", channel="in_app", title="Commande",
        body="Nouvelle commande", status="unread", action_url="/online-admin-ui#order-42",
    )
    db.add(row)
    db.commit()
    return row


def test_revalidation_disables_old_subscription_without_send(client, db, monkeypatch):
    assert subscribe(client).status_code == 201
    row = notification(db)
    # The same name now resolves privately: creation-time validation is insufficient.
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", Mock(return_value=dns_answers("10.0.0.1")))
    sender = Mock()
    assert web_push.dispatch_web_push_for_notification(db=db, notification=row, sender=sender) == {
        "attempted": 0, "sent": 0, "failed": 1,
    }
    sender.assert_not_called()
    db.expire_all()
    assert db.query(WebPushSubscription).one().is_active is False
    assert db.query(OnlineNotification).one().status == "unread"


def test_invalid_legacy_subscription_does_not_affect_other_tenant(db):
    for merchant in (2, 3):
        db.add(WebPushSubscription(merchant_id=merchant, endpoint=f"http://localhost/{merchant}", p256dh="p", auth="a", is_active=True))
    db.commit()
    sender = Mock()
    web_push.dispatch_web_push_for_notification(db=db, notification=notification(db), sender=sender)
    sender.assert_not_called()
    assert db.query(WebPushSubscription).filter_by(merchant_id=2).one().is_active is False
    assert db.query(WebPushSubscription).filter_by(merchant_id=3).one().is_active is True


def test_only_active_subscriptions_of_notification_tenant_are_sent(db):
    for number, (merchant, active) in enumerate([(2, True), (2, False), (3, True)]):
        db.add(WebPushSubscription(merchant_id=merchant, endpoint=f"{ENDPOINT}/{number}", p256dh="p", auth="a", is_active=active))
    db.commit()
    sender = Mock()
    result = web_push.dispatch_web_push_for_notification(db=db, notification=notification(db), sender=sender)
    assert result == {"attempted": 1, "sent": 1, "failed": 0}
    assert sender.call_args.args[0]["endpoint"] == ENDPOINT + "/0"


def test_invalid_subscription_is_disabled_after_durable_materialization(db, monkeypatch):
    db.add(WebPushSubscription(merchant_id=2, endpoint="http://localhost/private", p256dh="p", auth="a", is_active=True))
    db.add(OutboxEvent(
        event_id="00000000-0000-0000-0000-000000000702", merchant_id=2,
        aggregate_type="online_order", aggregate_id="42", event_type="notification.requested",
        event_version=1, payload={"data": {"channel": "in_app", "recipient_role": "merchant", "message": "Order"}},
        status="pending", retry_count=0,
    ))
    db.commit()
    transport = Mock(side_effect=AssertionError("Invalid endpoint must not reach transport"))
    monkeypatch.setattr(web_push, "PinnedPushSession", transport)
    assert worker.materialize_notification_batch(db=db, merchant_id=2)["published"] == 1
    db.rollback()
    assert db.query(WebPushSubscription).one().is_active is False
    assert db.query(OnlineNotification).one().status == "unread"
    assert db.query(OutboxEvent).one().status == "published"
    transport.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("provider failed"), ValueError("push failed")])
def test_push_error_preserves_published_batch_and_notifications(db, monkeypatch, error):
    for number in (1, 2):
        db.add(OutboxEvent(
            event_id=f"00000000-0000-0000-0000-{number:012d}", merchant_id=2,
            aggregate_type="online_order", aggregate_id=str(number), event_type="notification.requested",
            event_version=1, payload={"data": {"channel": "in_app", "recipient_role": "merchant", "message": "Order"}},
            status="pending", retry_count=0,
        ))
    db.commit()
    monkeypatch.setattr(worker, "dispatch_web_push_for_notification", Mock(side_effect=error))
    assert worker.materialize_notification_batch(db=db, merchant_id=2) == {
        "claimed": 2, "published": 2, "retried": 0, "failed": 0,
    }
    db.rollback()
    assert db.query(OnlineNotification).count() == 2
    assert all(row.status == "published" for row in db.query(OutboxEvent).all())
    assert worker.dispatch_web_push_for_notification.call_count == 2


@pytest.fixture
def ephemeral_keys():
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    private = ec.generate_private_key(ec.SECP256R1())
    receiver = ec.generate_private_key(ec.SECP256R1())
    subscription = {
        "endpoint": ENDPOINT,
        "keys": {
            "p256dh": encode(receiver.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
            "auth": encode(b"fixture-auth-key!"),
        },
    }
    return private, subscription, encode


def response(status=201, location=None):
    result = requests.Response()
    result.status_code = status
    result._content = b""
    if location:
        result.headers["Location"] = location
    return result


@pytest.mark.parametrize("key_format", ["raw", "der-pkcs8", "der-sec1", "pem-file"])
def test_installed_pywebpush_accepts_real_key_formats(ephemeral_keys, tmp_path, key_format):
    from pywebpush import webpush

    private, subscription, encode = ephemeral_keys
    if key_format == "raw":
        key = encode(private.private_numbers().private_value.to_bytes(32, "big"))
    elif key_format.startswith("der"):
        fmt = serialization.PrivateFormat.PKCS8 if key_format == "der-pkcs8" else serialization.PrivateFormat.TraditionalOpenSSL
        key = encode(private.private_bytes(serialization.Encoding.DER, fmt, serialization.NoEncryption()))
    else:
        path = tmp_path / "ephemeral.pem"
        path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key = str(path)
    transport = Mock()
    transport.post.return_value = response()
    result = webpush(subscription, data="test", vapid_private_key=key,
                     vapid_claims={"sub": "mailto:test@example.test"}, requests_session=transport)
    assert result.status_code == 201
    assert transport.post.call_count == 1
    assert bool(transport.post.call_args.kwargs["headers"].get("Authorization"))


def test_default_pywebpush_follows_redirects_without_custom_transport(ephemeral_keys):
    from pywebpush import webpush

    class RecordingAdapter(BaseAdapter):
        def __init__(self):
            self.urls = []

        def send(self, request, **kwargs):
            self.urls.append(request.url)
            result = response(307, "https://127.0.0.1/private") if len(self.urls) == 1 else response()
            result.request = request
            result.url = request.url
            return result

        def close(self):
            pass

    _, subscription, _ = ephemeral_keys
    adapter = RecordingAdapter()
    with requests.Session() as session:
        session.trust_env = False
        session.mount("https://", adapter)
        webpush(subscription, data="test", requests_session=session)
    assert adapter.urls == [ENDPOINT, "https://127.0.0.1/private"]


@pytest.mark.parametrize("status", [201, 301, 302, 303, 307, 308])
def test_secure_pywebpush_accepts_success_but_never_follows_redirects(monkeypatch, ephemeral_keys, status):
    from pywebpush import WebPushException

    private, subscription, encode = ephemeral_keys
    monkeypatch.setenv("WEB_PUSH_VAPID_PRIVATE_KEY", encode(private.private_numbers().private_value.to_bytes(32, "big")))
    pool = Mock()
    pool.__enter__ = Mock(return_value=pool)
    pool.__exit__ = Mock(return_value=False)
    pool.urlopen.return_value = HTTPResponse(
        body=io.BytesIO(b""), status=status, headers={"Location": "https://127.0.0.1/private"}, preload_content=False,
    )
    factory = Mock(return_value=pool)
    monkeypatch.setattr(push_endpoint.urllib3, "HTTPSConnectionPool", factory)
    if status == 201:
        assert web_push._send(subscription, {"body": "test"}).status_code == 201
    else:
        with pytest.raises(WebPushException):
            web_push._send(subscription, {"body": "test"})
    assert pool.urlopen.call_count == 1
    options = pool.urlopen.call_args.kwargs
    assert options["redirect"] is False and options["retries"] is False
    assert options["headers"]["Host"] == "fcm.googleapis.com"
    assert factory.call_args.kwargs["host"] == "8.8.8.8"
    assert factory.call_args.kwargs["server_hostname"] == "fcm.googleapis.com"
    assert factory.call_args.kwargs["assert_hostname"] == "fcm.googleapis.com"
    assert factory.call_args.kwargs["cert_reqs"] == ssl.CERT_REQUIRED


def test_inline_pem_is_not_an_accepted_vapid_string(ephemeral_keys):
    from py_vapid import Vapid

    private, _, _ = ephemeral_keys
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    with pytest.raises(ValueError):
        Vapid.from_string(pem)


def test_connection_uses_pinned_ip_not_rebound_hostname(monkeypatch):
    import urllib3.util.connection

    dns = Mock(side_effect=[dns_answers("8.8.8.8"), dns_answers("127.0.0.1")])
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", dns)
    connect = Mock(side_effect=OSError("Network intentionally blocked"))
    monkeypatch.setattr(urllib3.util.connection, "create_connection", connect)
    # Even malicious proxy environment variables must not affect this transport.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    with push_endpoint.PinnedPushSession(ENDPOINT) as session:
        with pytest.raises(Exception):
            session.post(ENDPOINT, data=b"encrypted test")
    assert dns.call_count == 1
    assert connect.call_count == 1
    assert connect.call_args.args[0] == ("8.8.8.8", 443)


def test_send_itself_revalidates_and_rejects_before_pywebpush(monkeypatch, ephemeral_keys):
    import pywebpush

    _, subscription, _ = ephemeral_keys
    push_endpoint.validate_push_endpoint(ENDPOINT)
    monkeypatch.setattr(push_endpoint.socket, "getaddrinfo", Mock(return_value=dns_answers("127.0.0.1")))
    send = Mock()
    monkeypatch.setattr(pywebpush, "webpush", send)
    with pytest.raises(push_endpoint.InvalidPushEndpoint):
        web_push._send(subscription, {"body": "test"})
    send.assert_not_called()
