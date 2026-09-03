import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.models.merchant import Merchant
from app.models.product import Product


TEST_SECRET = "test-pwa-tenant-secret-" + ("x" * 32)


@pytest.fixture()
def tenant_client(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PWA_JWT_TTL_SECONDS", "3600")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Merchant.__table__.create(engine)
    Product.__table__.create(engine)

    TestSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestSession()

    merchant_a = Merchant(
        whatsapp_number="+22997000001",
        shop_name="Boutique A",
        subscription_status="pilot",
        password_hash=hash_password("PasswordA123!"),
    )

    merchant_b = Merchant(
        whatsapp_number="+22997000002",
        shop_name="Boutique B",
        subscription_status="pilot",
        password_hash=hash_password("PasswordB123!"),
    )

    db.add_all([merchant_a, merchant_b])
    db.commit()
    db.refresh(merchant_a)
    db.refresh(merchant_b)

    token_a = create_access_token(merchant_a)
    token_b = create_access_token(merchant_b)

    ids = {
        "a": merchant_a.id,
        "b": merchant_b.id,
    }

    db.close()

    def override_get_db():
        test_db = TestSession()
        try:
            yield test_db
        finally:
            test_db.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)

    yield client, token_a, token_b, ids, TestSession

    app.dependency_overrides.clear()
    engine.dispose()


def auth(token: str):
    return {
        "Authorization": f"Bearer {token}",
    }


def test_pwa_products_requires_jwt(tenant_client):
    client, _, _, _, _ = tenant_client

    response = client.get("/pwa/products")

    assert response.status_code == 401


def test_admin_products_still_requires_admin_token(
    tenant_client,
):
    client, _, _, _, _ = tenant_client

    response = client.get("/products")

    assert response.status_code == 403


def test_each_merchant_only_sees_own_products(
    tenant_client,
):
    client, token_a, token_b, ids, TestSession = tenant_client

    response_a = client.post(
        "/pwa/products",
        headers=auth(token_a),
        json={
            "name": "Riz A",
            "unit": "sac",
            "stock": 10,
            "purchase_price": 10000,
            "price": 12000,
        },
    )

    assert response_a.status_code == 200

    response_b = client.post(
        "/pwa/products",
        headers=auth(token_b),
        json={
            "name": "Riz B",
            "unit": "sac",
            "stock": 20,
            "purchase_price": 11000,
            "price": 13000,
        },
    )

    assert response_b.status_code == 200

    list_a = client.get(
        "/pwa/products",
        headers=auth(token_a),
    )

    list_b = client.get(
        "/pwa/products",
        headers=auth(token_b),
    )

    assert list_a.status_code == 200
    assert list_b.status_code == 200

    assert [p["name"] for p in list_a.json()] == [
        "Riz A"
    ]

    assert [p["name"] for p in list_b.json()] == [
        "Riz B"
    ]

    db = TestSession()
    rows = (
        db.query(Product)
        .order_by(Product.id.asc())
        .all()
    )

    assert rows[0].merchant_id == ids["a"]
    assert rows[1].merchant_id == ids["b"]

    db.close()


def test_merchant_cannot_modify_other_product(
    tenant_client,
):
    client, token_a, token_b, _, _ = tenant_client

    created = client.post(
        "/pwa/products",
        headers=auth(token_b),
        json={
            "name": "Produit B",
            "unit": "pièce",
            "stock": 5,
            "purchase_price": 500,
            "price": 700,
        },
    )

    assert created.status_code == 200

    product_b_id = created.json()["id"]

    attack = client.patch(
        f"/pwa/products/{product_b_id}",
        headers=auth(token_a),
        json={
            "price": 1,
        },
    )

    assert attack.status_code == 404
    assert attack.json() == {
        "detail": "Produit introuvable",
    }

    check_b = client.get(
        "/pwa/products",
        headers=auth(token_b),
    )

    assert check_b.status_code == 200
    assert check_b.json()[0]["price"] == 700
