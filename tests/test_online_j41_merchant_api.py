import pytest
from app.online_main import app
from app.merchant.identity import resolve_merchant_identity
from tests.merchant_j41_support import environment, merchant, login, notification, HEADERS
from tests.test_online_j2_order_admin import _make_order

@pytest.fixture
def env():
    db, client = environment()
    yield db, client
    app.dependency_overrides.clear(); client.close(); db.close()

@pytest.mark.parametrize('method,path', [('get','bootstrap'),('get','dashboard'),('get','orders'),('get','notifications'),('patch','notifications/1/read'),('get','push/config'),('post','push-subscriptions')])
def test_no_identity_fails_closed(env, method, path):
    _, client = env
    response = getattr(client, method)(f'/merchant-api/{path}')
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store, private'
    assert 'merchant_id' not in response.text


def test_real_commerce_dashboard_and_badge(env):
    db, client = env
    row, order = _make_order(db, suffix='j41', customer_name='Alice', customer_phone='+229111')
    login(row); item = notification(db, row)
    bootstrap = client.get('/merchant-api/bootstrap').json()
    assert bootstrap['merchant']['display_name'] == 'Shop j41'
    assert 'catalog' in bootstrap['capabilities']
    assert bootstrap['notifications']['unread_count'] == 1
    assert 'merchant_id' not in str(bootstrap)
    dashboard = client.get('/merchant-api/dashboard').json()
    assert dashboard['stats'][0] == {'label':'À confirmer', 'value':1}
    assert dashboard['recent_orders'][0]['reference'] == order['reference']
    assert 'customer_phone' not in str(dashboard)
    assert client.patch(f'/merchant-api/notifications/{item.id}/read', json={}, headers=HEADERS).status_code == 200
    assert client.get('/merchant-api/bootstrap').json()['notifications']['unread_count'] == 0
    assert client.get('/merchant-api/notifications').json()['items'][0]['read'] is True

@pytest.mark.parametrize('kind,label', [('restaurant','Restaurant'),('rental','Location')])
def test_other_verticals_no_fabricated_metrics(env, kind, label):
    db, client = env
    row, _ = merchant(db, kind=kind); login(row)
    assert client.get('/merchant-api/bootstrap').json()['merchant']['business_label'] == label
    dashboard = client.get('/merchant-api/dashboard').json()
    assert dashboard['recent_orders'] == []
    assert not {'bookings','deposits','preparation_time'} & dashboard.keys()
    if kind == 'rental': assert dashboard['stats'] == []
    else: assert all(s['value'] == 0 for s in dashboard['stats'])


def test_roles_and_capabilities(env):
    db, client = env
    row, _ = merchant(db, capabilities=[]); login(row, role='customer')
    assert client.get('/merchant-api/bootstrap').status_code == 403
    login(row)
    for route in ('orders','notifications','push/config'):
        assert client.get(f'/merchant-api/{route}').status_code == 403


def test_unknown_type_endpoint(env):
    db, client = env
    row, store = merchant(db); store.business_type = 'future'; db.commit(); login(row)
    response = client.get('/merchant-api/bootstrap')
    assert response.status_code == 200 and response.json()['configuration_required']


def test_csrf_required_and_errors_private(env):
    db, client = env
    row, _ = merchant(db); item = notification(db,row); login(row)
    for headers in ({}, {'origin':'https://evil.test','x-merchant-request':'1'}, {'origin':'http://testserver'}, {**HEADERS,'sec-fetch-site':'cross-site'}):
        assert client.patch(f'/merchant-api/notifications/{item.id}/read', json={}, headers=headers).status_code == 403
    response = client.get('/merchant-api/orders?limit=not-a-number')
    assert response.status_code == 422 and 'not-a-number' not in response.text


def test_push_uses_existing_validation_and_sanitizes_body(env, monkeypatch):
    db, client = env
    row, _ = merchant(db); login(row)
    monkeypatch.setattr('app.routers.merchant_api.web_push_enabled', lambda: True)
    response = client.post('/merchant-api/push-subscriptions', json={'endpoint':'http://127.0.0.1/push','keys':{'p256dh':'p'*32,'auth':'a'*16}}, headers=HEADERS)
    assert response.status_code in (422,503)
    assert '127.0.0.1' not in response.text
    response = client.post('/merchant-api/push-subscriptions', json={'endpoint':'invalid','keys':{'auth':'do-not-echo'}}, headers=HEADERS)
    assert response.status_code == 422 and 'do-not-echo' not in response.text


def test_cross_origin_reads_refused_even_with_session(env):
    db, client = env
    row, _ = merchant(db); login(row)
    response = client.get('/merchant-api/bootstrap', headers={'origin':'https://evil.test'})
    assert response.status_code == 403
    assert 'Awa Market' not in response.text


def test_safe_whatsapp_handoff_only_on_order_detail(env):
    db, client = env
    row, order = _make_order(db, suffix='handoff', customer_name='Client', customer_phone='+22997000000')
    login(row)
    detail = client.get(f'/merchant-api/orders?order_id={order["id"]}').json()['items'][0]
    assert detail['whatsapp_url'].startswith('https://wa.me/22997000000?text=')
    assert 'whatsapp_url' not in client.get('/merchant-api/orders').json()['items'][0]


def test_push_registration_bound_to_identity_and_no_reassignment(env, monkeypatch):
    from app.shared.notifications.push_model import WebPushSubscription
    db, client = env
    a, _ = merchant(db, name='Push A'); b, _ = merchant(db, name='Push B')
    monkeypatch.setattr('app.routers.merchant_api.web_push_enabled', lambda: True)
    monkeypatch.setenv('WEB_PUSH_ALLOWED_HOST_SUFFIXES', 'example.test')
    monkeypatch.setattr('app.shared.notifications.push_endpoint.socket.getaddrinfo', lambda *args, **kwargs: [(2,1,6,'',('8.8.8.8',443))])
    payload = {'endpoint':'https://push.example.test/subscription/test','keys':{'p256dh':'p'*32,'auth':'a'*16}}
    login(a)
    assert client.post('/merchant-api/push-subscriptions', json=payload, headers=HEADERS).status_code == 201
    assert db.query(WebPushSubscription).one().merchant_id == a.id
    login(b)
    response = client.post('/merchant-api/push-subscriptions', json=payload, headers=HEADERS)
    assert response.status_code == 409 and 'endpoint' not in response.text
    assert db.query(WebPushSubscription).one().merchant_id == a.id


def test_storefront_health_and_discovery_routes_still_respond(env):
    from app.domains.online.internal.models import OnlineStore
    from app.domains.online.internal.catalog_models import OnlineProductPublication
    db, client = env
    row, order = _make_order(db, suffix='compatibility', customer_name='Client', customer_phone='+22997000000')
    store = db.query(OnlineStore).filter_by(merchant_id=row.id).one()
    product = db.query(OnlineProductPublication).filter_by(merchant_id=row.id).one()
    paths = ['/health', '/robots.txt', '/sitemap.xml', '/online-admin-ui', '/online-admin-sw.js',
             f'/shop/{store.slug}', f'/shop/{store.slug}/p/{product.seo_slug}',
             f'/shop/{store.slug}/order/{order["reference"]}?phone=%2B22997000000']
    for path in paths:
        assert client.get(path).status_code == 200, path
