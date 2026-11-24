from fastapi.testclient import TestClient

from app.main import app


def test_stock_360_route_is_mounted_under_pwa():
    with TestClient(app) as client:
        response = client.get("/pwa/stock/360")

    # La route existe : sans authentification elle doit être protégée,
    # donc surtout pas répondre 404.
    assert response.status_code == 401


def test_stock_360_is_not_exposed_without_pwa_prefix():
    with TestClient(app) as client:
        response = client.get("/stock/360")

    assert response.status_code == 404
