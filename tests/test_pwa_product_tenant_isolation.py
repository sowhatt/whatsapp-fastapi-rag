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
from app.models.product_barcode import ProductBarcode
from app.models.product_reference import ProductReference
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory


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
    Shop.__table__.create(engine)
    ShopInventory.__table__.create(engine)
    ProductBarcode.__table__.create(engine)
    ProductReference.__table__.create(engine)

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


def test_merchant_cannot_restock_other_product(
    tenant_client,
):
    client, token_a, token_b, _, _ = tenant_client

    created = client.post(
        "/pwa/products",
        headers=auth(token_b),
        json={
            "name": "Airwaves B",
            "unit": "unité",
            "stock": 5,
            "purchase_price": 500,
            "price": 700,
        },
    )

    assert created.status_code == 200

    product_b_id = created.json()["id"]

    attack = client.post(
        f"/pwa/products/{product_b_id}/restock",
        headers=auth(token_a),
        json={
            "quantity": 10,
            "purchase_price": 450,
            "source": "manual",
            "note": "Tentative cross-tenant",
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

    product_b = next(
        product
        for product in check_b.json()
        if product["id"] == product_b_id
    )

    assert product_b["stock"] == 5
    assert product_b["purchase_price"] == 500


# ============================================================
# P1-D — Protection contre les doublons produit
# ============================================================


def _create_p1d_product(
    client,
    token: str,
    name: str,
    *,
    stock: int = 0,
):
    return client.post(
        "/pwa/products",
        headers=auth(token),
        json={
            "name": name,
            "unit": "unité",
            "stock": stock,
            "purchase_price": 500,
            "price": 1000,
            "threshold": 0,
        },
    )


def test_duplicate_product_name_is_case_insensitive(
    tenant_client,
):
    client, token_a, _, _, _ = tenant_client

    first = _create_p1d_product(
        client,
        token_a,
        "Coca Duplicate Guard",
    )

    assert first.status_code == 200

    duplicate = _create_p1d_product(
        client,
        token_a,
        "coca duplicate guard",
    )

    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "detail": "Ce produit existe déjà dans votre catalogue.",
    }


def test_duplicate_product_name_ignores_extra_spaces(
    tenant_client,
):
    client, token_a, _, _, _ = tenant_client

    first = _create_p1d_product(
        client,
        token_a,
        "Fanta Duplicate Guard",
    )

    assert first.status_code == 200

    duplicate = _create_p1d_product(
        client,
        token_a,
        "   Fanta Duplicate Guard   ",
    )

    assert duplicate.status_code == 409


def test_product_cannot_be_renamed_to_existing_name(
    tenant_client,
):
    client, token_a, _, _, _ = tenant_client

    coca = _create_p1d_product(
        client,
        token_a,
        "Coca Rename Guard",
    )
    fanta = _create_p1d_product(
        client,
        token_a,
        "Fanta Rename Guard",
    )

    assert coca.status_code == 200
    assert fanta.status_code == 200

    response = client.patch(
        f"/pwa/products/{fanta.json()['id']}",
        headers=auth(token_a),
        json={
            "name": "coca rename guard",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail":
            "Un autre produit porte déjà ce nom dans votre catalogue.",
    }


def test_product_can_keep_same_name_with_spaces(
    tenant_client,
):
    client, token_a, _, _, _ = tenant_client

    created = _create_p1d_product(
        client,
        token_a,
        "Sprite Rename Same",
    )

    assert created.status_code == 200

    product_id = created.json()["id"]

    response = client.patch(
        f"/pwa/products/{product_id}",
        headers=auth(token_a),
        json={
            "name": "   Sprite Rename Same   ",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Sprite Rename Same"


def test_same_product_name_is_allowed_for_different_merchants(
    tenant_client,
):
    client, token_a, token_b, _, _ = tenant_client

    product_a = _create_p1d_product(
        client,
        token_a,
        "Coca Shared Name",
    )

    product_b = _create_p1d_product(
        client,
        token_b,
        "Coca Shared Name",
    )

    assert product_a.status_code == 200
    assert product_b.status_code == 200

    assert product_a.json()["id"] != product_b.json()["id"]


def test_barcode_cannot_be_associated_to_two_products_same_merchant(
    tenant_client,
):
    from fastapi import HTTPException

    from app.routers.pwa_smart_catalog import associate_catalog_barcode

    client, token_a, _, ids, TestSession = tenant_client

    product_a = _create_p1d_product(
        client,
        token_a,
        "Barcode Product A",
    )

    product_b = _create_p1d_product(
        client,
        token_a,
        "Barcode Product B",
    )

    assert product_a.status_code == 200
    assert product_b.status_code == 200

    db = TestSession()

    shop = Shop(
        merchant_id=ids["a"],
        name="Boutique Barcode",
        code="barcode-test",
    )
    db.add(shop)
    db.commit()
    db.refresh(shop)

    db.info["pwa_shop_id"] = shop.id
    db.info["resolved_shop_id"] = shop.id

    barcode = "1234567890123"

    first = associate_catalog_barcode(
        barcode=barcode,
        product_id=product_a.json()["id"],
        db=db,
    )

    assert first.source == "merchant_barcode"

    try:
        associate_catalog_barcode(
            barcode=barcode,
            product_id=product_b.json()["id"],
            db=db,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert (
            exc.detail
            == "Ce code-barres est déjà associé à un autre produit de ce commerçant."
        )
    else:
        raise AssertionError(
            "L'association du même EAN à deux produits aurait dû être refusée."
        )

    db.close()
