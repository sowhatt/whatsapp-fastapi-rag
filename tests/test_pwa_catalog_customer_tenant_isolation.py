import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.models.category import Category
from app.models.customer import Customer
from app.models.merchant import Merchant


TEST_SECRET = "test-pwa-lot3a-secret-" + ("x" * 32)


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
    Category.__table__.create(engine)
    Customer.__table__.create(engine)

    TestSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestSession()

    merchant_a = Merchant(
        whatsapp_number="+22997000101",
        shop_name="Boutique A",
        subscription_status="pilot",
        password_hash=hash_password("PasswordA123!"),
    )

    merchant_b = Merchant(
        whatsapp_number="+22997000102",
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

    db.close()

    def override_get_db():
        test_db = TestSession()
        try:
            yield test_db
        finally:
            test_db.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)

    yield client, token_a, token_b, TestSession

    app.dependency_overrides.clear()
    engine.dispose()


def auth(token: str):
    return {
        "Authorization": f"Bearer {token}",
    }


def test_categories_are_tenant_isolated(
    tenant_client,
):
    client, token_a, token_b, _ = tenant_client

    a = client.post(
        "/pwa/categories",
        headers=auth(token_a),
        json={"name": "Boissons A"},
    )
    b = client.post(
        "/pwa/categories",
        headers=auth(token_b),
        json={"name": "Boissons B"},
    )

    assert a.status_code == 200
    assert b.status_code == 200

    list_a = client.get(
        "/pwa/categories",
        headers=auth(token_a),
    )
    list_b = client.get(
        "/pwa/categories",
        headers=auth(token_b),
    )

    assert [c["name"] for c in list_a.json()] == [
        "Boissons A"
    ]
    assert [c["name"] for c in list_b.json()] == [
        "Boissons B"
    ]


def test_customers_are_tenant_isolated(
    tenant_client,
):
    client, token_a, token_b, _ = tenant_client

    a = client.post(
        "/pwa/customers",
        headers=auth(token_a),
        json={
            "name": "Client A",
            "phone": "+22961000101",
            "debt": 1200,
        },
    )

    b = client.post(
        "/pwa/customers",
        headers=auth(token_b),
        json={
            "name": "Client B",
            "phone": "+22961000102",
            "debt": 2400,
        },
    )

    assert a.status_code == 200
    assert b.status_code == 200

    list_a = client.get(
        "/pwa/customers",
        headers=auth(token_a),
    )
    list_b = client.get(
        "/pwa/customers",
        headers=auth(token_b),
    )

    assert [c["name"] for c in list_a.json()] == [
        "Client A"
    ]
    assert [c["name"] for c in list_b.json()] == [
        "Client B"
    ]


def test_debtors_are_tenant_isolated(
    tenant_client,
):
    client, token_a, token_b, _ = tenant_client

    client.post(
        "/pwa/customers",
        headers=auth(token_a),
        json={
            "name": "Débiteur A",
            "phone": "+22962000101",
            "debt": 5000,
        },
    )

    client.post(
        "/pwa/customers",
        headers=auth(token_b),
        json={
            "name": "Débiteur B",
            "phone": "+22962000102",
            "debt": 9000,
        },
    )

    debtors_a = client.get(
        "/pwa/customers/debtors",
        headers=auth(token_a),
    )

    debtors_b = client.get(
        "/pwa/customers/debtors",
        headers=auth(token_b),
    )

    assert [c["name"] for c in debtors_a.json()] == [
        "Débiteur A"
    ]
    assert [c["name"] for c in debtors_b.json()] == [
        "Débiteur B"
    ]


def test_merchant_cannot_read_other_customer_debt(
    tenant_client,
):
    client, token_a, token_b, _ = tenant_client

    created_b = client.post(
        "/pwa/customers",
        headers=auth(token_b),
        json={
            "name": "Secret B",
            "phone": "+22963000102",
            "debt": 7500,
        },
    )

    assert created_b.status_code == 200

    customer_b_id = created_b.json()["id"]

    attack = client.get(
        f"/pwa/customers/{customer_b_id}/debt",
        headers=auth(token_a),
    )

    assert attack.status_code == 404
    assert attack.json() == {
        "detail": "Client introuvable",
    }

    own = client.get(
        f"/pwa/customers/{customer_b_id}/debt",
        headers=auth(token_b),
    )

    assert own.status_code == 200
    assert own.json()["debt"] == 7500


def test_pwa_catalog_routes_require_jwt(
    tenant_client,
):
    client, _, _, _ = tenant_client

    assert client.get(
        "/pwa/categories"
    ).status_code == 401

    assert client.get(
        "/pwa/customers"
    ).status_code == 401
