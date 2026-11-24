import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models.activation_invitation import ActivationInvitation
from app.models.admin_user import AdminUser
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.auth import hash_password
from app.services.admin_auth_service import create_admin_access_token


ADMIN_JWT_SECRET = "test-admin-jwt-secret-for-invitation-0123456789"
PHONE = "+22997003001"
PASSWORD = "PiloteHTTP123!"


@pytest.fixture()
def invitation_client(monkeypatch):
    monkeypatch.setenv("ADMIN_JWT_SECRET", ADMIN_JWT_SECRET)
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

    AdminUser.__table__.create(engine)
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

    db = TestingSession()
    admin = AdminUser(
        email="superadmin@whatzabi.test",
        full_name="Super Admin Test",
        password_hash=hash_password("AdminPassword123!"),
        role="SUPER_ADMIN",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    global ADMIN_JWT
    ADMIN_JWT = create_admin_access_token(admin)

    db.close()

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
    return {"Authorization": f"Bearer {ADMIN_JWT}"}


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


def test_invite_requires_admin_jwt(invitation_client):
    response = invitation_client.post(
        "/admin/pilots/invite",
        json=invite_payload(),
    )

    assert response.status_code == 401


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
    merchant_id = data["pilot"]["merchant_id"]

    # L'Admin voit immédiatement le pilote en attente d'activation.
    pending_pilot = invitation_client.get(
        f"/admin/pilots/{merchant_id}",
        headers=admin_headers(),
    )

    assert pending_pilot.status_code == 200, pending_pilot.text

    pending_data = pending_pilot.json()

    assert pending_data["onboarding_status"] == "pending_activation"
    assert pending_data["user_count"] == 1
    assert pending_data["activation"]["status"] == "pending"
    assert pending_data["activation"]["invited_at"] is not None
    assert pending_data["activation"]["expires_at"] is not None
    assert pending_data["activation"]["activated_at"] is None
    assert "token_hash" not in pending_data["activation"]

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

    # Après activation, l'Admin voit le pilote comme actif.
    active_pilot = invitation_client.get(
        f"/admin/pilots/{merchant_id}",
        headers=admin_headers(),
    )

    assert active_pilot.status_code == 200, active_pilot.text

    active_data = active_pilot.json()

    assert active_data["onboarding_status"] == "active"
    assert active_data["user_count"] == 1
    assert active_data["owner"]["active"] is True
    assert active_data["activation"]["status"] == "activated"
    assert active_data["activation"]["activated_at"] is not None
    assert "token_hash" not in active_data["activation"]

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


def test_admin_can_reinvite_existing_pending_pilot(invitation_client):
    first = invitation_client.post(
        "/admin/pilots/invite",
        headers=admin_headers(),
        json=invite_payload(),
    )
    assert first.status_code == 201, first.text

    first_data = first.json()
    merchant_id = first_data["pilot"]["merchant_id"]
    first_token = first_data["activation"]["token"]

    reinvite = invitation_client.post(
        f"/admin/pilots/{merchant_id}/reinvite",
        headers=admin_headers(),
        json={"invitation_hours": 72},
    )
    assert reinvite.status_code == 200, reinvite.text

    data = reinvite.json()

    # On réutilise strictement le pilote existant.
    assert data["pilot"]["merchant_id"] == merchant_id
    assert data["pilot"]["merchant_name"] == invite_payload()["merchant_name"]
    assert data["pilot"]["owner"]["name"] == invite_payload()["owner_name"]
    assert data["pilot"]["onboarding_status"] == "pending_activation"

    # Une nouvelle invitation est générée.
    second_token = data["activation"]["token"]
    assert second_token
    assert second_token != first_token
    assert data["activation"]["status"] == "pending_activation"
    assert data["activation"]["expires_at"] is not None

    # L'ancien lien a été révoqué.
    old_activation = invitation_client.post(
        "/auth/activate",
        json={
            "token": first_token,
            "password": PASSWORD,
        },
    )
    assert old_activation.status_code == 410, old_activation.text
    assert (
        old_activation.json()["detail"]["code"]
        == "invitation_revoked"
    )

    # Le nouveau lien reste utilisable.
    new_activation = invitation_client.post(
        "/auth/activate",
        json={
            "token": second_token,
            "password": PASSWORD,
        },
    )
    assert new_activation.status_code == 200, new_activation.text
