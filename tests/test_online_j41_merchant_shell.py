import pytest
from fastapi.testclient import TestClient
from app.online_main import app

@pytest.mark.parametrize('route', ['/merchant', '/merchant/', '/merchant/orders', '/merchant/notifications', '/merchant/catalog', '/merchant/module/kitchen', '/merchant/module/calendar'])
def test_direct_refresh_shell(route):
    response = TestClient(app).get(route)
    assert response.status_code == 200
    assert 'Whatzabi' in response.text and 'type="module"' in response.text
    assert 'frame-ancestors' in response.headers['content-security-policy']


def test_technical_cockpit_preserved():
    assert TestClient(app).get('/online-admin-ui').status_code == 200
