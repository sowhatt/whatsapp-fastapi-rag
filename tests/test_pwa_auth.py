import os

import jwt
import pytest

from app.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.merchant import Merchant


TEST_SECRET = "test-pwa-secret-" + ("x" * 32)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PWA_JWT_TTL_SECONDS", "3600")


def test_hash_password_is_not_plain_text():
    encoded = hash_password("MotDePasse123!")

    assert encoded != "MotDePasse123!"
    assert encoded.startswith("scrypt$")


def test_verify_password_accepts_correct_password():
    encoded = hash_password("MotDePasse123!")

    assert verify_password("MotDePasse123!", encoded) is True


def test_verify_password_rejects_wrong_password():
    encoded = hash_password("MotDePasse123!")

    assert verify_password("MauvaisPasse123!", encoded) is False


def test_short_password_is_rejected():
    with pytest.raises(ValueError):
        hash_password("court")


def test_access_token_contains_merchant_identity():
    merchant = Merchant(
        id=42,
        whatsapp_number="+22997000000",
        shop_name="Boutique test",
        subscription_status="pilot",
    )

    token = create_access_token(merchant)

    payload = jwt.decode(
        token,
        TEST_SECRET,
        algorithms=["HS256"],
    )

    assert payload["sub"] == "42"
    assert payload["merchant_id"] == 42
    assert payload["type"] == "access"
    assert payload["exp"] > payload["iat"]


def test_jwt_secret_is_required(monkeypatch):
    monkeypatch.delenv("PWA_JWT_SECRET", raising=False)

    merchant = Merchant(
        id=1,
        whatsapp_number="+22997000001",
        shop_name="Test",
        subscription_status="pilot",
    )

    with pytest.raises(RuntimeError):
        create_access_token(merchant)
