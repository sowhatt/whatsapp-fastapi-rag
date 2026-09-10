from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.product import Product
from app.models.shop import Shop
from app.models.supplier import Supplier
from app.models.user_shop_membership import UserShopMembership
from app.routers.pwa_voice import MAX_AUDIO_BYTES


JWT_SECRET = "test-secret-for-pwa-voice-route-1234567890"


@pytest.fixture
def voice_client(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", JWT_SECRET)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    db = SessionLocal()

    merchant = Merchant(
        whatsapp_number="22900000031",
        shop_name="Boutique Voice",
        subscription_status="pilot",
    )
    db.add(merchant)
    db.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name="Centre",
        code="centre",
    )
    db.add(shop)
    db.flush()

    user = MerchantUser(
        merchant_id=merchant.id,
        full_name="Awa Voice",
        role="MANAGER",
        password_hash=hash_password("motdepasse123"),
        is_active=True,
    )
    db.add(user)
    db.flush()

    db.add(
        UserShopMembership(
            user_id=user.id,
            shop_id=shop.id,
            role="MANAGER",
            is_active=True,
        )
    )

    db.add_all(
        [
            Product(
                merchant_id=merchant.id,
                name="Riz parfumé",
                unit="sac",
                stock=20,
                purchase_price=12000,
                price=18000,
                threshold=2,
            ),
            Customer(
                merchant_id=merchant.id,
                name="Awa",
                phone="+22997000000",
            ),
            Supplier(
                merchant_id=merchant.id,
                name="Grossiste Lagos",
                phone="+2348000000000",
            ),
        ]
    )

    db.commit()

    token_with_shop = create_access_token(
        merchant,
        user_id=user.id,
        shop_id=shop.id,
        role="MANAGER",
    )

    token_without_shop = create_access_token(
        merchant,
        user_id=user.id,
        role="MANAGER",
    )

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)

    yield {
        "client": client,
        "token_with_shop": token_with_shop,
        "token_without_shop": token_without_shop,
    }

    app.dependency_overrides.clear()
    db.close()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_pwa_voice_requires_auth(voice_client):
    client = voice_client["client"]

    response = client.post(
        "/pwa/voice/transcribe",
        files={"audio": ("voice.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 401


def test_pwa_voice_requires_selected_shop(voice_client):
    client = voice_client["client"]
    token = voice_client["token_without_shop"]

    response = client.post(
        "/pwa/voice/transcribe",
        headers=auth(token),
        files={"audio": ("voice.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 409
    assert "boutique" in response.json()["detail"].lower()


def test_pwa_voice_rejects_unsupported_format(voice_client):
    client = voice_client["client"]
    token = voice_client["token_with_shop"]

    response = client.post(
        "/pwa/voice/transcribe",
        headers=auth(token),
        files={"audio": ("voice.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415


def test_pwa_voice_rejects_empty_audio(voice_client):
    client = voice_client["client"]
    token = voice_client["token_with_shop"]

    response = client.post(
        "/pwa/voice/transcribe",
        headers=auth(token),
        files={"audio": ("voice.webm", b"", "audio/webm")},
    )

    assert response.status_code == 400


def test_pwa_voice_rejects_audio_too_large(voice_client):
    client = voice_client["client"]
    token = voice_client["token_with_shop"]

    response = client.post(
        "/pwa/voice/transcribe",
        headers=auth(token),
        files={
            "audio": (
                "voice.webm",
                b"x" * (MAX_AUDIO_BYTES + 1),
                "audio/webm",
            )
        },
    )

    assert response.status_code == 413


def test_pwa_voice_transcribes_with_catalog_vocabulary(voice_client):
    client = voice_client["client"]
    token = voice_client["token_with_shop"]

    with patch(
        "app.routers.pwa_voice.transcribe_audio_bytes",
        return_value="J'ai vendu trois sacs de riz à Awa",
    ) as mocked_transcribe:
        response = client.post(
            "/pwa/voice/transcribe",
            headers=auth(token),
            files={
                "audio": (
                    "voice.webm",
                    b"fake-audio-bytes",
                    "audio/webm",
                )
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "transcribed",
        "text": "J'ai vendu trois sacs de riz à Awa",
    }

    args, kwargs = mocked_transcribe.call_args

    assert args[0] == b"fake-audio-bytes"
    assert args[1] == "audio/webm"

    vocabulary = kwargs["vocabulary"]

    assert "Riz parfumé" in vocabulary
    assert "Awa" in vocabulary
    assert "Grossiste Lagos" in vocabulary
