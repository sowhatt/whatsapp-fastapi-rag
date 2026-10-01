import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership


ADMIN_TOKEN = "test-admin-token"
PHONE = "+22997001001"
PASSWORD = "PilotPassword123!"


@pytest.fixture()
def admin_client(monkeypatch):
    monkeypatch.setenv(
        "ADMIN_TOKEN",
        ADMIN_TOKEN,
    )
    monkeypatch.setenv(
        "PWA_JWT_SECRET",
        "test-pwa-jwt-secret-for-pilot-access-0123456789",
    )

    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
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

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(
            get_db,
            None,
        )
        engine.dispose()


def admin_headers():
    return {
        "X-Admin-Token": ADMIN_TOKEN,
    }


def pilot_payload():
    return {
        "whatsapp_number": PHONE,
        "merchant_name": "Boutique Pilote 01",
        "owner_name": "Pilote 01",
        "password": PASSWORD,
        "country_code": "BJ",
        "currency_code": "XOF",
        "duration_days": 30,
    }


def test_admin_pilots_requires_admin_token(
    admin_client,
):
    response = admin_client.get(
        "/admin/pilots",
    )

    assert response.status_code == 403


def test_create_pilot_requires_admin_token(
    admin_client,
):
    response = admin_client.post(
        "/admin/pilots",
        json=pilot_payload(),
    )

    assert response.status_code == 403


def test_admin_can_create_pilot(
    admin_client,
):
    response = admin_client.post(
        "/admin/pilots",
        headers=admin_headers(),
        json=pilot_payload(),
    )

    assert response.status_code == 201

    data = response.json()

    assert data["merchant_name"] == "Boutique Pilote 01"
    assert data["subscription_status"] == "pilot"
    assert data["country_code"] == "BJ"

    assert data["owner"]["name"] == "Pilote 01"
    assert data["owner"]["active"] is True

    assert data["shop"]["name"] == "Boutique Pilote 01"
    assert data["shop"]["currency_code"] == "XOF"
    assert data["shop"]["active"] is True


def test_duplicate_pilot_phone_returns_409(
    admin_client,
):
    first = admin_client.post(
        "/admin/pilots",
        headers=admin_headers(),
        json=pilot_payload(),
    )

    assert first.status_code == 201

    second = admin_client.post(
        "/admin/pilots",
        headers=admin_headers(),
        json=pilot_payload(),
    )

    assert second.status_code == 409

    assert (
        second.json()["detail"]["code"]
        == "phone_already_registered"
    )


def test_admin_can_list_and_get_pilot(
    admin_client,
):
    created = admin_client.post(
        "/admin/pilots",
        headers=admin_headers(),
        json=pilot_payload(),
    )

    assert created.status_code == 201

    merchant_id = created.json()["merchant_id"]

    listing = admin_client.get(
        "/admin/pilots",
        headers=admin_headers(),
    )

    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = admin_client.get(
        f"/admin/pilots/{merchant_id}",
        headers=admin_headers(),
    )

    assert detail.status_code == 200
    assert detail.json()["merchant_id"] == merchant_id


def test_admin_can_suspend_and_reactivate_pilot(
    admin_client,
):
    created = admin_client.post(
        "/admin/pilots",
        headers=admin_headers(),
        json=pilot_payload(),
    )

    merchant_id = created.json()["merchant_id"]

    suspended = admin_client.post(
        f"/admin/pilots/{merchant_id}/suspend",
        headers=admin_headers(),
    )

    assert suspended.status_code == 200
    assert (
        suspended.json()["subscription_status"]
        == "suspended"
    )

    reactivated = admin_client.post(
        f"/admin/pilots/{merchant_id}/reactivate",
        headers=admin_headers(),
    )

    assert reactivated.status_code == 200
    assert (
        reactivated.json()["subscription_status"]
        == "pilot"
    )


def test_admin_can_extend_pilot(
    admin_client,
):
    created = admin_client.post(
        "/admin/pilots",
        headers=admin_headers(),
        json=pilot_payload(),
    )

    assert created.status_code == 201

    merchant_id = created.json()["merchant_id"]
    before = created.json()["subscription_ends_at"]

    extended = admin_client.post(
        f"/admin/pilots/{merchant_id}/extend",
        headers=admin_headers(),
        json={
            "days": 15,
        },
    )

    assert extended.status_code == 200

    after = extended.json()["subscription_ends_at"]

    assert after != before


def test_unknown_pilot_returns_404(
    admin_client,
):
    response = admin_client.get(
        "/admin/pilots/999999",
        headers=admin_headers(),
    )

    assert response.status_code == 404


def test_complete_pilot_access_lifecycle(
    admin_client,
):
    # 1. L'administrateur crée le pilote.
    created = admin_client.post(
        "/admin/pilots",
        headers=admin_headers(),
        json=pilot_payload(),
    )

    assert created.status_code == 201

    merchant_id = created.json()["merchant_id"]

    # 2. Le commerçant se connecte à Whatzabi.
    login = admin_client.post(
        "/auth/login",
        json={
            "whatsapp_number": PHONE,
            "password": PASSWORD,
        },
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    # 3. Son JWT permet d'accéder à son contexte PWA.
    me = admin_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert me.status_code == 200
    assert me.json()["id"] == merchant_id

    # 4. L'administrateur suspend le pilote.
    suspended = admin_client.post(
        f"/admin/pilots/{merchant_id}/suspend",
        headers=admin_headers(),
    )

    assert suspended.status_code == 200
    assert (
        suspended.json()["subscription_status"]
        == "suspended"
    )

    # 5. Le JWT déjà émis est immédiatement refusé.
    blocked = admin_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert blocked.status_code == 403
    assert (
        blocked.json()["detail"]["code"]
        == "subscription_inactive"
    )

    # 6. Même une nouvelle tentative de connexion est refusée.
    blocked_login = admin_client.post(
        "/auth/login",
        json={
            "whatsapp_number": PHONE,
            "password": PASSWORD,
        },
    )

    assert blocked_login.status_code == 403

    # 7. L'administrateur réactive le pilote.
    reactivated = admin_client.post(
        f"/admin/pilots/{merchant_id}/reactivate",
        headers=admin_headers(),
    )

    assert reactivated.status_code == 200
    assert (
        reactivated.json()["subscription_status"]
        == "pilot"
    )

    # 8. Le commerçant peut de nouveau se connecter.
    login_again = admin_client.post(
        "/auth/login",
        json={
            "whatsapp_number": PHONE,
            "password": PASSWORD,
        },
    )

    assert login_again.status_code == 200

    new_token = login_again.json()["access_token"]

    # 9. Et retrouver son contexte.
    me_again = admin_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {new_token}",
        },
    )

    assert me_again.status_code == 200
    assert me_again.json()["id"] == merchant_id
