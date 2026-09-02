import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db.session import get_db
from app.main import app
from app.models.merchant import Merchant


TEST_SECRET = "test-pwa-http-secret-" + ("x" * 32)
TEST_PHONE = "+22997000000"
TEST_PASSWORD = "MotDePasse123!"


@pytest.fixture()
def auth_client(monkeypatch):
    monkeypatch.setenv(
        "PWA_JWT_SECRET",
        TEST_SECRET,
    )
    monkeypatch.setenv(
        "PWA_JWT_TTL_SECONDS",
        "3600",
    )

    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Merchant.__table__.create(engine)

    TestSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestSession()
    merchant = Merchant(
        whatsapp_number=TEST_PHONE,
        shop_name="Boutique HTTP test",
        subscription_status="pilot",
        password_hash=hash_password(
            TEST_PASSWORD,
        ),
    )
    db.add(merchant)
    db.commit()
    db.close()

    def override_get_db():
        test_db = TestSession()
        try:
            yield test_db
        finally:
            test_db.close()

    app.dependency_overrides[get_db] = (
        override_get_db
    )

    client = TestClient(app)

    yield client

    app.dependency_overrides.clear()
    engine.dispose()


def test_login_returns_access_token(auth_client):
    response = auth_client.post(
        "/auth/login",
        json={
            "whatsapp_number": TEST_PHONE,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["merchant"]["whatsapp_number"] == (
        TEST_PHONE
    )
    assert body["merchant"]["shop_name"] == (
        "Boutique HTTP test"
    )
    assert body["merchant"]["subscription_status"] == (
        "pilot"
    )


def test_login_rejects_wrong_password(auth_client):
    response = auth_client.post(
        "/auth/login",
        json={
            "whatsapp_number": TEST_PHONE,
            "password": "MauvaisPasse123!",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Identifiants invalides",
    }


def test_login_rejects_unknown_merchant(auth_client):
    response = auth_client.post(
        "/auth/login",
        json={
            "whatsapp_number": "+22999999999",
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 401


def test_me_returns_authenticated_merchant(
    auth_client,
):
    login = auth_client.post(
        "/auth/login",
        json={
            "whatsapp_number": TEST_PHONE,
            "password": TEST_PASSWORD,
        },
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    response = auth_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 200
    assert response.json()["whatsapp_number"] == (
        TEST_PHONE
    )
    assert response.json()["shop_name"] == (
        "Boutique HTTP test"
    )


def test_me_rejects_missing_token(auth_client):
    response = auth_client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentification requise",
    }


def test_me_rejects_invalid_token(auth_client):
    response = auth_client.get(
        "/auth/me",
        headers={
            "Authorization": "Bearer faux-token",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Jeton invalide",
    }


def test_me_rejects_wrong_token_type(
    auth_client,
):
    import jwt

    token = jwt.encode(
        {
            "sub": "1",
            "merchant_id": 1,
            "type": "refresh",
        },
        TEST_SECRET,
        algorithm="HS256",
    )

    response = auth_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Jeton invalide",
    }


def test_me_rejects_wrong_token_type(
    auth_client,
):
    import jwt

    token = jwt.encode(
        {
            "sub": "1",
            "merchant_id": 1,
            "type": "refresh",
        },
        TEST_SECRET,
        algorithm="HS256",
    )

    response = auth_client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Jeton invalide",
    }
