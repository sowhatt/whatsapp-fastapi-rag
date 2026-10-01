import pytest

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password, require_pwa_merchant
from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.routers.auth import router as auth_router
from app.routers.pwa_staff import router as staff_router


TEST_SECRET = "test-staff-http-secret-" + ("x" * 32)

OWNER_PHONE = "+22997003001"
OWNER_PASSWORD = "OwnerPassword123!"

SELLER_PHONE = "+22997003002"
SELLER_PASSWORD = "SellerPassword123!"

MANAGER_PHONE = "+22997003003"
MANAGER_PASSWORD = "ManagerPassword123!"


@pytest.fixture()
def staff_client(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PWA_JWT_TTL_SECONDS", "3600")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Merchant.__table__.create(engine)
    MerchantUser.__table__.create(engine)
    Shop.__table__.create(engine)
    UserPhone.__table__.create(engine)
    UserShopMembership.__table__.create(engine)

    TestingSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestingSession()

    merchant = Merchant(
        whatsapp_number=OWNER_PHONE,
        shop_name="Boutique Staff HTTP",
        country_code="BJ",
        subscription_status="pilot",
        password_hash=hash_password(OWNER_PASSWORD),
    )
    db.add(merchant)
    db.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name="Boutique Staff HTTP",
        code="STAFF-HTTP",
        currency_code="XOF",
        is_active=True,
    )
    db.add(shop)
    db.flush()

    owner = MerchantUser(
        merchant_id=merchant.id,
        full_name="Owner HTTP",
        role="OWNER",
        password_hash=hash_password(OWNER_PASSWORD),
        is_active=True,
    )
    db.add(owner)
    db.flush()

    owner_phone = UserPhone(
        merchant_id=merchant.id,
        user_id=owner.id,
        shop_id=shop.id,
        phone_number=OWNER_PHONE,
        is_primary=True,
        is_active=True,
    )
    db.add(owner_phone)

    owner_membership = UserShopMembership(
        user_id=owner.id,
        shop_id=shop.id,
        role="OWNER",
        is_active=True,
    )
    db.add(owner_membership)

    db.commit()

    merchant_id = merchant.id
    shop_id = shop.id

    db.close()

    def override_get_db():
        test_db = TestingSession()
        try:
            yield test_db
        finally:
            test_db.close()

    test_app = FastAPI()

    test_app.include_router(auth_router)

    test_app.include_router(
        staff_router,
        prefix="/pwa",
        dependencies=[Depends(require_pwa_merchant)],
    )

    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as client:
        yield {
            "client": client,
            "Session": TestingSession,
            "merchant_id": merchant_id,
            "shop_id": shop_id,
        }

    engine.dispose()


def login(client, phone, password):
    return client.post(
        "/auth/login",
        json={
            "whatsapp_number": phone,
            "password": password,
        },
    )


def bearer(token):
    return {
        "Authorization": f"Bearer {token}",
    }


def owner_token(client):
    response = login(
        client,
        OWNER_PHONE,
        OWNER_PASSWORD,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["merchant"]["role"] == "OWNER"

    return body["access_token"]


def create_staff(
    client,
    token,
    *,
    full_name,
    phone_number,
    password,
    role,
):
    return client.post(
        "/pwa/staff",
        headers=bearer(token),
        json={
            "full_name": full_name,
            "phone_number": phone_number,
            "password": password,
            "role": role,
        },
    )


def test_owner_can_create_seller_and_seller_can_login(
    staff_client,
):
    client = staff_client["client"]

    token = owner_token(client)

    created = create_staff(
        client,
        token,
        full_name="Seller HTTP",
        phone_number=SELLER_PHONE,
        password=SELLER_PASSWORD,
        role="SELLER",
    )

    assert created.status_code == 201

    body = created.json()

    assert body["full_name"] == "Seller HTTP"
    assert body["role"] == "SELLER"
    assert body["is_active"] is True
    assert body["shop_id"] == staff_client["shop_id"]

    seller_login = login(
        client,
        SELLER_PHONE,
        SELLER_PASSWORD,
    )

    assert seller_login.status_code == 200

    seller = seller_login.json()["merchant"]

    assert seller["role"] == "SELLER"
    assert seller["shop_id"] == staff_client["shop_id"]


def test_seller_cannot_list_staff(
    staff_client,
):
    client = staff_client["client"]

    token = owner_token(client)

    created = create_staff(
        client,
        token,
        full_name="Seller HTTP",
        phone_number=SELLER_PHONE,
        password=SELLER_PASSWORD,
        role="SELLER",
    )

    assert created.status_code == 201

    seller_login = login(
        client,
        SELLER_PHONE,
        SELLER_PASSWORD,
    )

    assert seller_login.status_code == 200

    seller_token = seller_login.json()["access_token"]

    response = client.get(
        "/pwa/staff",
        headers=bearer(seller_token),
    )

    assert response.status_code == 403


def test_manager_can_list_but_cannot_manage_staff(
    staff_client,
):
    client = staff_client["client"]

    token = owner_token(client)

    manager = create_staff(
        client,
        token,
        full_name="Manager HTTP",
        phone_number=MANAGER_PHONE,
        password=MANAGER_PASSWORD,
        role="MANAGER",
    )

    assert manager.status_code == 201

    manager_login = login(
        client,
        MANAGER_PHONE,
        MANAGER_PASSWORD,
    )

    assert manager_login.status_code == 200

    manager_token = manager_login.json()["access_token"]

    listing = client.get(
        "/pwa/staff",
        headers=bearer(manager_token),
    )

    assert listing.status_code == 200

    forbidden = create_staff(
        client,
        manager_token,
        full_name="Seller Interdit",
        phone_number="+22997003004",
        password="Password123!",
        role="SELLER",
    )

    assert forbidden.status_code == 403


def test_owner_can_change_seller_to_manager(
    staff_client,
):
    client = staff_client["client"]

    token = owner_token(client)

    created = create_staff(
        client,
        token,
        full_name="Seller HTTP",
        phone_number=SELLER_PHONE,
        password=SELLER_PASSWORD,
        role="SELLER",
    )

    assert created.status_code == 201

    user_id = created.json()["id"]

    changed = client.patch(
        f"/pwa/staff/{user_id}/role",
        headers=bearer(token),
        json={"role": "MANAGER"},
    )

    assert changed.status_code == 200
    assert changed.json()["role"] == "MANAGER"

    relogin = login(
        client,
        SELLER_PHONE,
        SELLER_PASSWORD,
    )

    assert relogin.status_code == 200
    assert relogin.json()["merchant"]["role"] == "MANAGER"


def test_staff_suspension_invalidates_old_jwt_and_login(
    staff_client,
):
    client = staff_client["client"]

    token = owner_token(client)

    created = create_staff(
        client,
        token,
        full_name="Seller HTTP",
        phone_number=SELLER_PHONE,
        password=SELLER_PASSWORD,
        role="SELLER",
    )

    assert created.status_code == 201

    user_id = created.json()["id"]

    seller_login = login(
        client,
        SELLER_PHONE,
        SELLER_PASSWORD,
    )

    assert seller_login.status_code == 200

    seller_token = seller_login.json()["access_token"]

    suspended = client.post(
        f"/pwa/staff/{user_id}/suspend",
        headers=bearer(token),
    )

    assert suspended.status_code == 200
    assert suspended.json()["is_active"] is False

    old_jwt = client.get(
        "/auth/me",
        headers=bearer(seller_token),
    )

    assert old_jwt.status_code == 401

    blocked_login = login(
        client,
        SELLER_PHONE,
        SELLER_PASSWORD,
    )

    assert blocked_login.status_code == 401


def test_owner_can_reactivate_staff(
    staff_client,
):
    client = staff_client["client"]

    token = owner_token(client)

    created = create_staff(
        client,
        token,
        full_name="Seller HTTP",
        phone_number=SELLER_PHONE,
        password=SELLER_PASSWORD,
        role="SELLER",
    )

    assert created.status_code == 201

    user_id = created.json()["id"]

    suspended = client.post(
        f"/pwa/staff/{user_id}/suspend",
        headers=bearer(token),
    )

    assert suspended.status_code == 200

    reactivated = client.post(
        f"/pwa/staff/{user_id}/reactivate",
        headers=bearer(token),
    )

    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True

    relogin = login(
        client,
        SELLER_PHONE,
        SELLER_PASSWORD,
    )

    assert relogin.status_code == 200
    assert relogin.json()["merchant"]["role"] == "SELLER"


def test_duplicate_staff_phone_returns_409(
    staff_client,
):
    client = staff_client["client"]

    token = owner_token(client)

    first = create_staff(
        client,
        token,
        full_name="Seller 1",
        phone_number=SELLER_PHONE,
        password=SELLER_PASSWORD,
        role="SELLER",
    )

    assert first.status_code == 201

    duplicate = create_staff(
        client,
        token,
        full_name="Seller 2",
        phone_number=SELLER_PHONE,
        password="AnotherPassword123!",
        role="SELLER",
    )

    assert duplicate.status_code == 409
    assert (
        duplicate.json()["detail"]["code"]
        == "phone_already_used"
    )


def test_owner_cannot_suspend_self(
    staff_client,
):
    client = staff_client["client"]

    login_response = login(
        client,
        OWNER_PHONE,
        OWNER_PASSWORD,
    )

    assert login_response.status_code == 200

    body = login_response.json()

    token = body["access_token"]
    owner_id = body["merchant"]["user_id"]

    response = client.post(
        f"/pwa/staff/{owner_id}/suspend",
        headers=bearer(token),
    )

    assert response.status_code == 400


def test_cross_merchant_staff_isolation(
    staff_client,
):
    client = staff_client["client"]
    Session = staff_client["Session"]

    token = owner_token(client)

    db = Session()

    merchant_b = Merchant(
        whatsapp_number="+22997004001",
        shop_name="Boutique B",
        country_code="BJ",
        subscription_status="pilot",
        password_hash=hash_password("MerchantB123!"),
    )
    db.add(merchant_b)
    db.flush()

    shop_b = Shop(
        merchant_id=merchant_b.id,
        name="Boutique B",
        code="STAFF-B",
        currency_code="XOF",
        is_active=True,
    )
    db.add(shop_b)
    db.flush()

    user_b = MerchantUser(
        merchant_id=merchant_b.id,
        full_name="Seller B",
        role="SELLER",
        password_hash=hash_password("SellerB123!"),
        is_active=True,
    )
    db.add(user_b)
    db.flush()

    phone_b = UserPhone(
        merchant_id=merchant_b.id,
        user_id=user_b.id,
        shop_id=shop_b.id,
        phone_number="+22997004002",
        is_primary=True,
        is_active=True,
    )
    db.add(phone_b)

    membership_b = UserShopMembership(
        user_id=user_b.id,
        shop_id=shop_b.id,
        role="SELLER",
        is_active=True,
    )
    db.add(membership_b)

    db.commit()

    foreign_user_id = user_b.id

    db.close()

    response = client.post(
        f"/pwa/staff/{foreign_user_id}/suspend",
        headers=bearer(token),
    )

    assert response.status_code == 404
