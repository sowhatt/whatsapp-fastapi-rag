import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models.activation_invitation import ActivationInvitation
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership


ADMIN_TOKEN = "test-admin-token"
PHONE = "+22997003001"
PASSWORD = "PiloteHTTP123!"


@pytest.fixture()
def invitation_client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv(
        "PWA_JWT_SECRET",
        "test-pwa-invitation-secret-" + ("x" * 32),
    )
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
    ActivationInvitation.__table__.create(engine)

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
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def admin_headers():
    return {"X-Admin-Token": ADMIN_TOKEN}


def invite_payload():
    return {
        "whatsapp_number": PHONE,
        "merchant_name": "Boutique HTTP Invitation",
        "owner_name": "Owner HTTP Invitation",
        "country_code": "BJ",
        "currency_code": "XOF",
        "duration_days": 30,
        "invitation_hours": 48,
    }


def test_invite_requires_admin_token(invitation_client):
    response = invitation_client.post(
        "/admin/pilots/invite",
        json=invite_payload(),
    )

    assert response.status_code == 403


def test_complete_invitation_activation_login_flow(invitation_client):
    invite = invitation_client.post(
        "/admin/pilots/invite",
        headers=admin_headers(),
        json=invite_payload(),
    )

    assert invite.status_code == 201, invite.text

    data = invite.json()

    assert data["activation"]["status"] == "pending_activation"
    assert data["activation"]["token"]
    assert data["pilot"]["owner"]["active"] is False

    token = data["activation"]["token"]

    # Le compte existe mais ne peut pas encore se connecter.
    before = invitation_client.post(
        "/auth/login",
        json={
            "whatsapp_number": PHONE,
            "password": PASSWORD,
        },
    )

    assert before.status_code == 401

    activation = invitation_client.post(
        "/auth/activate",
        json={
            "token": token,
            "password": PASSWORD,
        },
    )

    assert activation.status_code == 200, activation.text

    activation_data = activation.json()

    assert activation_data["activated"] is True
    assert (
        activation_data["merchant_id"]
        == data["pilot"]["merchant_id"]
    )
    assert (
        activation_data["user_id"]
        == data["pilot"]["owner"]["id"]
    )

    login = invitation_client.post(
        "/auth/login",
        json={
            "whatsapp_number": PHONE,
            "password": PASSWORD,
        },
    )

    assert login.status_code == 200, login.text

    login_data = login.json()

    assert (
        login_data["merchant"]["id"]
        == data["pilot"]["merchant_id"]
    )
    assert (
        login_data["merchant"]["user_id"]
        == data["pilot"]["owner"]["id"]
    )
    assert login_data["merchant"]["role"] == "OWNER"
    assert (
        login_data["merchant"]["shop_id"]
        == data["pilot"]["shop"]["id"]
    )

    access_token = login_data["access_token"]

    me = invitation_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
    )

    assert me.status_code == 200
    assert me.json()["role"] == "OWNER"

    # Une invitation consommée ne peut jamais être réutilisée.
    reuse = invitation_client.post(
        "/auth/activate",
        json={
            "token": token,
            "password": "AutrePassword123!",
        },
    )

    assert reuse.status_code == 410
    assert (
        reuse.json()["detail"]["code"]
        == "invitation_used"
    )


def test_duplicate_invitation_phone_returns_409(invitation_client):
    first = invitation_client.post(
        "/admin/pilots/invite",
        headers=admin_headers(),
        json=invite_payload(),
    )

    assert first.status_code == 201

    second = invitation_client.post(
        "/admin/pilots/invite",
        headers=admin_headers(),
        json=invite_payload(),
    )

    assert second.status_code == 409
    assert (
        second.json()["detail"]["code"]
        == "phone_already_registered"
    )


def test_invalid_activation_token_is_rejected(invitation_client):
    response = invitation_client.post(
        "/auth/activate",
        json={
            "token": "x" * 32,
            "password": PASSWORD,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_token"
