import pytest
from app.online_main import app
from app.shared.notifications.model import OnlineNotification
from tests.merchant_j41_support import environment, merchant, login, notification, HEADERS
from tests.test_online_j2_order_admin import _make_order

@pytest.fixture
def env():
    db, client = environment()
    yield db, client
    app.dependency_overrides.clear(); client.close(); db.close()


def test_orders_and_notifications_never_cross_tenants(env):
    db, client = env
    a, oa = _make_order(db, suffix='tenant-a', customer_name='Alice', customer_phone='+229111')
    b, ob = _make_order(db, suffix='tenant-b', customer_name='Bob', customer_phone='+229222')
    na, nb = notification(db,a), notification(db,b,title='PRIVATE B')
    notification(db,a,role='customer',channel='whatsapp_handoff',title='CUSTOMER ONLY')
    login(a)
    assert [o['id'] for o in client.get('/merchant-api/orders').json()['items']] == [oa['id']]
    assert client.get(f'/merchant-api/orders?order_id={ob["id"]}').status_code == 404
    assert client.get(f'/merchant-api/orders?order_id={oa["id"]}').status_code == 200
    response = client.get('/merchant-api/notifications')
    assert [n['id'] for n in response.json()['items']] == [na.id]
    assert 'PRIVATE B' not in response.text and 'CUSTOMER ONLY' not in response.text
    assert client.patch(f'/merchant-api/notifications/{nb.id}/read', json={}, headers=HEADERS).status_code == 404
    db.refresh(nb); assert nb.status == 'unread'
    login(b)
    assert [o['id'] for o in client.get('/merchant-api/orders').json()['items']] == [ob['id']]


def test_frontend_tenant_selectors_rejected(env):
    db, client = env
    row, _ = merchant(db); login(row)
    for query in ('merchant_id=999', 'tenant_id=999', 'business_type=rental'):
        assert client.get(f'/merchant-api/bootstrap?{query}').status_code == 400
    for header in ('x-merchant-id','x-tenant-id','x-admin-token'):
        assert client.get('/merchant-api/bootstrap',headers={header:'999'}).status_code == 400
    assert client.patch('/merchant-api/notifications/1/read', json={'merchant_id':999}, headers=HEADERS).status_code == 400
    assert client.post('/merchant-api/push-subscriptions', json={'merchant_id':999}, headers=HEADERS).status_code == 400


def test_rls_applied_before_store_lookup(env, monkeypatch):
    db, client = env
    row, _ = merchant(db); login(row)
    calls = []
    monkeypatch.setattr('app.merchant.identity.apply_rls_context', lambda session, **kw: calls.append((session,kw)))
    assert client.get('/merchant-api/bootstrap').status_code == 200
    assert calls == [(db, {'merchant_id':row.id})]
