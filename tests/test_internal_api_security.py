import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.security import require_admin_token


client = TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/products", None),
        ("GET", "/customers", None),
        ("GET", "/sales", None),
        ("GET", "/financial-entries", None),
        (
            "POST",
            "/whatsapp/send-test",
            {
                "to": "33600000000",
                "body": "test",
            },
        ),
        ("GET", "/debug/env", None),
        (
            "POST",
            "/admin/truncate-db",
            None,
        ),
    ],
)
def test_internal_routes_reject_missing_admin_token(
    method,
    path,
    payload,
):
    response = client.request(
        method,
        path,
        json=payload,
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Accès refusé",
    }


def test_health_remains_public():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }


def test_webhook_verification_remains_public(
    monkeypatch,
):
    monkeypatch.setenv(
        "WHATSAPP_VERIFY_TOKEN",
        "test-webhook-token",
    )

    response = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": (
                "test-webhook-token"
            ),
            "hub.challenge": "123456",
        },
    )

    assert response.status_code == 200
    assert response.json() == 123456


def test_webhook_receiver_remains_public():
    response = client.post(
        "/webhooks/whatsapp",
        content=b"",
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ignored",
        "reason": "empty_body",
    }


def test_admin_token_fails_closed_when_not_configured(
    monkeypatch,
):
    monkeypatch.delenv(
        "ADMIN_TOKEN",
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        require_admin_token("anything")

    assert exc_info.value.status_code == 403


def test_admin_token_rejects_wrong_value(
    monkeypatch,
):
    monkeypatch.setenv(
        "ADMIN_TOKEN",
        "correct-secret",
    )

    with pytest.raises(HTTPException) as exc_info:
        require_admin_token("wrong-secret")

    assert exc_info.value.status_code == 403


def test_admin_token_accepts_exact_value(
    monkeypatch,
):
    monkeypatch.setenv(
        "ADMIN_TOKEN",
        "test-secret-token",
    )

    assert (
        require_admin_token(
            "test-secret-token",
        )
        is None
    )
