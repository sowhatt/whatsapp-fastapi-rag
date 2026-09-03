import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.merchant import Merchant
from app.models.payment import Payment
from app.models.sale import Sale


TEST_SECRET = "test-pwa-lot3b-secret-" + ("x" * 32)


@pytest.fixture()
def tenant_client(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PWA_JWT_TTL_SECONDS", "3600")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    TestSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestSession()

    merchant_a = Merchant(
        whatsapp_number="+22997000201",
        shop_name="Boutique A",
        subscription_status="pilot",
        password_hash=hash_password("PasswordA123!"),
    )

    merchant_b = Merchant(
        whatsapp_number="+22997000202",
        shop_name="Boutique B",
        subscription_status="pilot",
        password_hash=hash_password("PasswordB123!"),
    )

    db.add_all([merchant_a, merchant_b])
    db.commit()
    db.refresh(merchant_a)
    db.refresh(merchant_b)

    merchant_a_id = merchant_a.id
    merchant_b_id = merchant_b.id

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

    yield (
        client,
        token_a,
        token_b,
        merchant_a_id,
        merchant_b_id,
        TestSession,
    )

    app.dependency_overrides.clear()
    engine.dispose()


def auth(token):
    return {
        "Authorization": f"Bearer {token}",
    }


def create_customer(client, token, name, phone):
    response = client.post(
        "/pwa/customers",
        headers=auth(token),
        json={
            "name": name,
            "phone": phone,
            "debt": 0,
        },
    )

    assert response.status_code == 200, response.text
    return response.json()


def create_product(client, token, name):
    response = client.post(
        "/pwa/products",
        headers=auth(token),
        json={
            "name": name,
            "unit": "sac",
            "price": 1000,
            "purchase_price": 700,
            "stock": 20,
        },
    )

    assert response.status_code == 200, response.text
    return response.json()


def create_credit_sale(
    client,
    token,
    customer_id,
    product_id,
):
    response = client.post(
        "/pwa/sales",
        headers=auth(token),
        json={
            "customer_id": customer_id,
            "items": [
                {
                    "product_id": product_id,
                    "quantity": 2,
                }
            ],
            "paid_amount": 0,
            "payment_channel": "cash",
        },
    )

    assert response.status_code == 200, response.text
    return response.json()


def test_pwa_sales_and_payments_require_jwt(
    tenant_client,
):
    client, *_ = tenant_client

    assert client.get(
        "/pwa/sales"
    ).status_code == 401

    assert client.post(
        "/pwa/payments",
        json={
            "sale_id": 1,
            "amount": 100,
            "channel": "cash",
        },
    ).status_code == 401


def test_sales_are_isolated_between_merchants(
    tenant_client,
):
    (
        client,
        token_a,
        token_b,
        merchant_a_id,
        merchant_b_id,
        TestSession,
    ) = tenant_client

    customer_a = create_customer(
        client,
        token_a,
        "Client A",
        "+22961000201",
    )
    product_a = create_product(
        client,
        token_a,
        "Riz A",
    )

    customer_b = create_customer(
        client,
        token_b,
        "Client B",
        "+22961000202",
    )
    product_b = create_product(
        client,
        token_b,
        "Riz B",
    )

    sale_a = create_credit_sale(
        client,
        token_a,
        customer_a["id"],
        product_a["id"],
    )

    sale_b = create_credit_sale(
        client,
        token_b,
        customer_b["id"],
        product_b["id"],
    )

    list_a = client.get(
        "/pwa/sales",
        headers=auth(token_a),
    )
    list_b = client.get(
        "/pwa/sales",
        headers=auth(token_b),
    )

    assert list_a.status_code == 200
    assert list_b.status_code == 200

    assert [s["id"] for s in list_a.json()] == [
        sale_a["id"]
    ]
    assert [s["id"] for s in list_b.json()] == [
        sale_b["id"]
    ]

    db = TestSession()
    try:
        row_a = db.get(Sale, sale_a["id"])
        row_b = db.get(Sale, sale_b["id"])

        assert row_a.merchant_id == merchant_a_id
        assert row_b.merchant_id == merchant_b_id
    finally:
        db.close()


def test_merchant_cannot_sell_to_other_customer(
    tenant_client,
):
    client, token_a, token_b, *_ = tenant_client

    customer_b = create_customer(
        client,
        token_b,
        "Client Secret B",
        "+22962000202",
    )

    product_a = create_product(
        client,
        token_a,
        "Maïs A",
    )

    attack = client.post(
        "/pwa/sales",
        headers=auth(token_a),
        json={
            "customer_id": customer_b["id"],
            "items": [
                {
                    "product_id": product_a["id"],
                    "quantity": 1,
                }
            ],
            "paid_amount": 0,
        },
    )

    assert attack.status_code == 404
    assert attack.json() == {
        "detail": "Client introuvable",
    }


def test_merchant_cannot_sell_other_product(
    tenant_client,
):
    client, token_a, token_b, *_ = tenant_client

    customer_a = create_customer(
        client,
        token_a,
        "Client Produit A",
        "+22963000201",
    )

    product_b = create_product(
        client,
        token_b,
        "Produit Secret B",
    )

    attack = client.post(
        "/pwa/sales",
        headers=auth(token_a),
        json={
            "customer_id": customer_a["id"],
            "items": [
                {
                    "product_id": product_b["id"],
                    "quantity": 1,
                }
            ],
            "paid_amount": 0,
        },
    )

    assert attack.status_code == 404
    assert attack.json() == {
        "detail": (
            f"Produit introuvable : "
            f"{product_b['id']}"
        ),
    }


def test_foreign_sale_details_are_not_visible(
    tenant_client,
):
    client, token_a, token_b, *_ = tenant_client

    customer_b = create_customer(
        client,
        token_b,
        "Client Vente B",
        "+22964000202",
    )
    product_b = create_product(
        client,
        token_b,
        "Igname B",
    )

    sale_b = create_credit_sale(
        client,
        token_b,
        customer_b["id"],
        product_b["id"],
    )

    items_attack = client.get(
        f"/pwa/sales/{sale_b['id']}/items",
        headers=auth(token_a),
    )

    payments_attack = client.get(
        f"/pwa/sales/{sale_b['id']}/payments",
        headers=auth(token_a),
    )

    assert items_attack.status_code == 404
    assert items_attack.json() == {
        "detail": "Vente introuvable",
    }

    assert payments_attack.status_code == 404
    assert payments_attack.json() == {
        "detail": "Vente introuvable",
    }


def test_merchant_cannot_cancel_foreign_sale(
    tenant_client,
):
    client, token_a, token_b, *_ = tenant_client

    customer_b = create_customer(
        client,
        token_b,
        "Client Annulation B",
        "+22965000202",
    )
    product_b = create_product(
        client,
        token_b,
        "Haricot B",
    )

    sale_b = create_credit_sale(
        client,
        token_b,
        customer_b["id"],
        product_b["id"],
    )

    attack = client.post(
        f"/pwa/sales/{sale_b['id']}/cancel",
        headers=auth(token_a),
        json={
            "reason": "attaque inter-tenant",
        },
    )

    assert attack.status_code == 404
    assert attack.json() == {
        "detail": "Vente introuvable",
    }

    own_sale = client.get(
        "/pwa/sales",
        headers=auth(token_b),
    )

    assert own_sale.status_code == 200
    assert own_sale.json()[0]["status"] != "cancelled"


def test_merchant_cannot_pay_foreign_sale(
    tenant_client,
):
    client, token_a, token_b, *_ = tenant_client

    customer_b = create_customer(
        client,
        token_b,
        "Client Paiement B",
        "+22966000202",
    )
    product_b = create_product(
        client,
        token_b,
        "Manioc B",
    )

    sale_b = create_credit_sale(
        client,
        token_b,
        customer_b["id"],
        product_b["id"],
    )

    attack = client.post(
        "/pwa/payments",
        headers=auth(token_a),
        json={
            "sale_id": sale_b["id"],
            "customer_id": customer_b["id"],
            "amount": 500,
            "channel": "cash",
        },
    )

    assert attack.status_code == 404
    assert attack.json() == {
        "detail": "Vente introuvable",
    }


def test_payment_rejects_customer_from_other_tenant(
    tenant_client,
):
    (
        client,
        token_a,
        token_b,
        _,
        _,
        TestSession,
    ) = tenant_client

    customer_a = create_customer(
        client,
        token_a,
        "Client Paiement A",
        "+22967000201",
    )
    product_a = create_product(
        client,
        token_a,
        "Fonio A",
    )

    customer_b = create_customer(
        client,
        token_b,
        "Client Injecté B",
        "+22967000202",
    )

    sale_a = create_credit_sale(
        client,
        token_a,
        customer_a["id"],
        product_a["id"],
    )

    attack = client.post(
        "/pwa/payments",
        headers=auth(token_a),
        json={
            "sale_id": sale_a["id"],
            "customer_id": customer_b["id"],
            "amount": 500,
            "channel": "cash",
        },
    )

    assert attack.status_code == 404
    assert attack.json() == {
        "detail": "Client introuvable",
    }

    db = TestSession()
    try:
        assert db.query(Payment).count() == 0

        sale = db.get(Sale, sale_a["id"])
        assert sale.paid_amount == 0
        assert sale.remaining_amount == 2000
        assert sale.status == "credit"
    finally:
        db.close()


def test_valid_payment_updates_own_sale(
    tenant_client,
):
    client, token_a, _, *_ = tenant_client

    customer_a = create_customer(
        client,
        token_a,
        "Client Paiement Valide",
        "+22968000201",
    )
    product_a = create_product(
        client,
        token_a,
        "Mil A",
    )

    sale_a = create_credit_sale(
        client,
        token_a,
        customer_a["id"],
        product_a["id"],
    )

    payment = client.post(
        "/pwa/payments",
        headers=auth(token_a),
        json={
            "sale_id": sale_a["id"],
            "customer_id": customer_a["id"],
            "amount": 500,
            "channel": "cash",
        },
    )

    assert payment.status_code == 200, payment.text
    assert payment.json()["amount"] == 500

    sales = client.get(
        "/pwa/sales",
        headers=auth(token_a),
    )

    assert sales.status_code == 200
    assert sales.json()[0]["paid_amount"] == 500
    assert sales.json()[0]["remaining_amount"] == 1500
    assert sales.json()[0]["status"] == "partial"
