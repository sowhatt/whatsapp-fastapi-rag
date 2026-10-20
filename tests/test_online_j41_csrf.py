"""Mutation guards tested after dependency override, not a real auth session."""
import pytest
from app.online_main import app
from tests.merchant_j41_support import environment, merchant, login, notification, HEADERS


@pytest.fixture
def env():
    db, client = environment()
    row, _ = merchant(db)
    login(row)
    item = notification(db, row)
    yield db, client, item
    app.dependency_overrides.clear()
    client.close()
    db.close()


@pytest.mark.parametrize('method,path,body', [
    ('patch', '/merchant-api/notifications/{id}/read', {}),
    ('post', '/merchant-api/push-subscriptions', {'endpoint': 'https://push.example.test/test', 'keys': {'p256dh': 'p'*32, 'auth':'a'*16}}),
])
@pytest.mark.parametrize('headers', [
    {},
    {'origin': 'http://testserver'},
    {'x-merchant-request': '1'},
    {**HEADERS, 'origin': 'https://other.test'},
    {**HEADERS, 'sec-fetch-site': 'cross-site'},
    {**HEADERS, 'sec-fetch-site': 'same-site'},
])
def test_cookie_style_mutations_need_same_origin_and_explicit_header(env, method, path, body, headers):
    db, client, item = env
    response = getattr(client, method)(path.format(id=item.id), json=body, headers=headers)
    assert response.status_code == 403
    db.refresh(item)
    assert item.status == 'unread'
