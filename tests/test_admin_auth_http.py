import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db.session import get_db
from app.models.admin_user import AdminUser
from app.routers.admin_auth import router as admin_auth_router


ADMIN_EMAIL = "admin@whatzabi.test"
ADMIN_PASSWORD = "AdminPassword123!"
ADMIN_JWT_SECRET = "test-admin-jwt-secret-01234567890123456789"


@pytest.fixture()
def admin_auth_client(monkeypatch):
    monkeypatch.setenv("ADMIN_JWT_SECRET", ADMIN_JWT_SECRET)
    monkeypatch.setenv("ADMIN_JWT_TTL_SECONDS", "3600")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    AdminUser.__table__.create(engine)

    TestingSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestingSession()
    admin = AdminUser(
        email=ADMIN_EMAIL,
        full_name="Super Admin Whatzabi",
        password_hash=hash_password(ADMIN_PASSWORD),
        role="SUPER_ADMIN",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.close()

    test_app = FastAPI()
    test_app.include_router(admin_auth_router)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(test_app) as client:
            yield client, TestingSession
    finally:
        engine.dispose()


def login(client):
    return client.post(
        "/admin/auth/login",
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        },
    )


def test_admin_can_login(admin_auth_client):
    client, _ = admin_auth_client

    response = login(client)

    assert response.status_code == 200

    data = response.json()

    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["admin"]["email"] == ADMIN_EMAIL
    assert data["admin"]["full_name"] == "Super Admin Whatzabi"
    assert data["admin"]["role"] == "SUPER_ADMIN"
    assert data["admin"]["is_active"] is True


def test_admin_login_normalizes_email(admin_auth_client):
    client, _ = admin_auth_client

    response = client.post(
        "/admin/auth/login",
        json={
            "email": f"  {ADMIN_EMAIL.upper()}  ",
            "password": ADMIN_PASSWORD,
        },
    )

    assert response.status_code == 200


def test_admin_login_rejects_wrong_password(admin_auth_client):
    client, _ = admin_auth_client

    response = client.post(
        "/admin/auth/login",
        json={
            "email": ADMIN_EMAIL,
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


def test_admin_me_requires_bearer_token(admin_auth_client):
    client, _ = admin_auth_client

    response = client.get("/admin/auth/me")

    assert response.status_code == 401


def test_admin_can_read_me(admin_auth_client):
    client, _ = admin_auth_client

    logged_in = login(client)
    token = logged_in.json()["access_token"]

    response = client.get(
        "/admin/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["email"] == ADMIN_EMAIL
    assert data["role"] == "SUPER_ADMIN"
    assert data["is_active"] is True


def test_invalid_admin_token_is_rejected(admin_auth_client):
    client, _ = admin_auth_client

    response = client.get(
        "/admin/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_admin_token"


def test_disabled_admin_cannot_login(admin_auth_client):
    client, TestingSession = admin_auth_client

    db = TestingSession()
    admin = db.query(AdminUser).filter(AdminUser.email == ADMIN_EMAIL).first()
    admin.is_active = False
    db.commit()
    db.close()

    response = login(client)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "admin_inactive"


def test_disabling_admin_invalidates_existing_token(admin_auth_client):
    client, TestingSession = admin_auth_client

    logged_in = login(client)
    assert logged_in.status_code == 200

    token = logged_in.json()["access_token"]

    db = TestingSession()
    admin = db.query(AdminUser).filter(AdminUser.email == ADMIN_EMAIL).first()
    admin.is_active = False
    db.commit()
    db.close()

    response = client.get(
        "/admin/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "admin_inactive"


def test_pwa_token_cannot_be_used_as_admin_token(admin_auth_client, monkeypatch):
    import jwt
    import time

    client, _ = admin_auth_client

    pwa_secret = "test-pwa-jwt-secret-for-pilot-access-0123456789"
    monkeypatch.setenv("PWA_JWT_SECRET", pwa_secret)

    now = int(time.time())

    pwa_token = jwt.encode(
        {
            "sub": "999",
            "merchant_id": 999,
            "user_id": 999,
            "role": "OWNER",
            "type": "access",
            "iat": now,
            "exp": now + 3600,
        },
        pwa_secret,
        algorithm="HS256",
    )

    response = client.get(
        "/admin/auth/me",
        headers={"Authorization": f"Bearer {pwa_token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_admin_token"
