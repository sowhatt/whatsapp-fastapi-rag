"""Service extraction regression: real persistence, original endpoint policy."""
import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.shared.notifications.push_model import WebPushSubscription
from app.shared.notifications import subscription_service as service


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def endpoint_policy(monkeypatch):
    monkeypatch.setenv('WEB_PUSH_ALLOWED_HOST_SUFFIXES', 'example.test')
    monkeypatch.setattr('app.shared.notifications.push_endpoint.socket.getaddrinfo',
                        lambda *args, **kwargs: [(2, 1, 6, '', ('8.8.8.8', 443))])


def payload(**overrides):
    return {'endpoint': 'https://push.example.test/test-subscription',
            'keys': {'p256dh': 'p' * 32, 'auth': 'a' * 16}, **overrides}


@pytest.mark.parametrize('raw', [None, [], {}, {'endpoint': 12},
    payload(merchant_id=2), payload(keys={'p256dh': 'p' * 32, 'auth': 'a' * 16, 'merchant_id': 2})])
def test_payload_is_closed_and_errors_are_sanitized(raw):
    with pytest.raises(service.SubscriptionError) as caught:
        service.parse_subscription_payload(raw)
    assert caught.value.status_code == 422
    assert caught.value.code == 'invalid_payload'
    assert str(caught.value) == 'Souscription Web Push invalide.'


def test_create_and_reactivate_keep_tenant_and_apply_rls(db, endpoint_policy, monkeypatch):
    calls = []
    monkeypatch.setattr(service, 'apply_rls_context', lambda session, **kwargs: calls.append(kwargs))
    result = service.save_subscription(merchant_id=1, payload=service.parse_subscription_payload(payload()), db=db)
    row = db.query(WebPushSubscription).one()
    assert row.merchant_id == 1 and result == {'id': row.id, 'active': True}
    row.is_active = False
    db.commit()
    renewed = service.save_subscription(merchant_id=1, payload=service.parse_subscription_payload(
        payload(keys={'p256dh': 'q' * 32, 'auth': 'b' * 16})), db=db)
    assert renewed == result and db.query(WebPushSubscription).count() == 1
    assert row.is_active and row.p256dh == 'q' * 32
    assert calls == [{'merchant_id': 1}] * 4


def test_endpoint_never_reassigned_and_failed_transaction_is_rolled_back(db, endpoint_policy):
    data = service.parse_subscription_payload(payload())
    service.save_subscription(merchant_id=1, payload=data, db=db)
    with pytest.raises(service.SubscriptionError) as caught:
        service.save_subscription(merchant_id=2, payload=data, db=db)
    assert caught.value.status_code == 409
    assert caught.value.code == 'subscription_unavailable'
    assert db.query(WebPushSubscription).one().merchant_id == 1


@pytest.mark.parametrize('endpoint', ['http://127.0.0.1/push', 'https://127.0.0.1/push', 'https://user:private@push.example.test/push', 'https://unlisted.invalid/push'])
def test_ssrf_validation_still_blocks_before_persistence(db, endpoint_policy, endpoint):
    with pytest.raises(service.SubscriptionError) as caught:
        service.save_subscription(merchant_id=1, payload=service.parse_subscription_payload(payload(endpoint=endpoint)), db=db)
    assert caught.value.status_code == 422
    assert db.query(WebPushSubscription).count() == 0
    assert endpoint not in str(caught.value)


def test_missing_endpoint_policy_fails_closed(db, monkeypatch):
    monkeypatch.delenv('WEB_PUSH_ALLOWED_HOST_SUFFIXES', raising=False)
    with pytest.raises(service.SubscriptionError) as caught:
        service.save_subscription(merchant_id=1, payload=service.parse_subscription_payload(payload()), db=db)
    assert caught.value.status_code == 503
    assert db.query(WebPushSubscription).count() == 0


def test_routers_depend_on_service_not_each_other():
    for file in ('app/routers/merchant_api.py', 'app/routers/online_admin.py'):
        tree = ast.parse(Path(file).read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert 'app.shared.notifications.subscription_service' in imports
        assert 'app.routers.online_admin' not in imports
