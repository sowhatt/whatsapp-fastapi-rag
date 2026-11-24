import logging
from types import SimpleNamespace
from datetime import datetime
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.routers import pwa_sale_photo as photo
from app.services import sale_photo_service as service


REQUEST_ID = "8b560fd6-bdf6-44a8-9a66-ce4dd8e515ae"
JPEG = b"\xff\xd8\xff" + b"test"


@pytest.fixture
def api(monkeypatch):
    # No real database or provider connection, including for auth failures.
    db = Mock(info={})
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=1)
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    monkeypatch.setattr(photo, "get_current_merchant", lambda db: 1)
    monkeypatch.setattr(photo, "get_current_shop_id", lambda db: 1)
    monkeypatch.setattr(photo, "create_photo_draft", lambda *a: SimpleNamespace(id="11111111-1111-4111-8111-111111111111", expires_at=datetime(2099, 1, 1)))
    analyzer = Mock(return_value={"lines": [], "warnings": []})
    monkeypatch.setattr(photo, "analyze_sale_photo", analyzer)
    app = FastAPI()

    def authenticate():
        pass

    # Same router dependency layout as main.py, without loading application startup.
    app.include_router(photo.router, prefix="/pwa", dependencies=[Depends(authenticate)])
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, analyzer, app, authenticate


def extract(client, data=JPEG, mime="image/jpeg", **kwargs):
    return client.post(
        "/pwa/sales/photo/extract",
        files={"image": ("private-customer-name.jpg", data, mime)},
        headers={"X-Request-ID": REQUEST_ID, "Authorization": "Bearer test-session"},
        **kwargs,
    )


def check_error(response, status, code):
    assert response.status_code == status
    assert response.headers["x-request-id"] == REQUEST_ID
    assert response.headers["cache-control"] == "no-store"
    error = response.json()["error"]
    assert error["request_id"] == REQUEST_ID
    assert error["code"] == code
    assert error["retryable"] == (status in (503, 504))


def test_auth_dependency_is_traced_without_disclosing_token(api, caplog):
    client, analyzer, app, authenticate = api

    def expired():
        raise HTTPException(401, "secret bearer token", headers={"WWW-Authenticate": "Bearer"})

    app.dependency_overrides[authenticate] = expired
    with caplog.at_level(logging.WARNING, logger=photo.__name__):
        response = extract(client)
    check_error(response, 401, "authentication_required")
    assert response.headers["www-authenticate"] == "Bearer"
    assert REQUEST_ID in caplog.text
    assert "secret bearer token" not in response.text + caplog.text
    assert "private-customer-name" not in caplog.text
    analyzer.assert_not_called()


def test_size_limit_and_exact_boundary(api):
    client, analyzer, _, _ = api
    check_error(extract(client, JPEG + b"x" * photo.MAX_BYTES), 413, "photo_too_large")
    analyzer.assert_not_called()
    assert extract(client, JPEG + b"x" * (photo.MAX_BYTES - len(JPEG))).status_code == 200


@pytest.mark.parametrize("data,mime", [
    (b"<svg>private-data</svg>", "image/jpeg"),
    (b"HEIC", "image/heic"),
    (b"RIFF", "image/webp"),
])
def test_unsupported_actual_format(api, data, mime):
    client, analyzer, _, _ = api
    check_error(extract(client, data, mime), 415, "unsupported_photo")
    analyzer.assert_not_called()


@pytest.mark.parametrize("data,mime", [
    (JPEG, "image/jpeg"),
    (b"\x89PNG\r\n\x1a\npayload", "image/png"),
    (b"RIFF1234WEBPpayload", "image/webp"),
])
def test_format_detected_from_bytes_not_filename_or_mime(api, data, mime):
    client, analyzer, _, _ = api
    response = extract(client, data, "application/octet-stream")
    assert response.status_code == 200
    assert response.headers["x-request-id"] == REQUEST_ID
    assert analyzer.call_args.args == (data, mime)


def test_empty_photo(api):
    client, analyzer, _, _ = api
    check_error(extract(client, b""), 400, "invalid_request")
    analyzer.assert_not_called()


@pytest.mark.parametrize("endpoint", ["extract", "confirm"])
def test_validation_error_never_echoes_payload(api, endpoint, caplog):
    client, analyzer, _, _ = api
    response = client.post(
        f"/pwa/sales/photo/{endpoint}",
        json={"private-customer-name": "private-payment-value"},
        headers={"X-Request-ID": REQUEST_ID},
    )
    check_error(response, 422, "validation_error")
    assert "private-customer-name" not in response.text + caplog.text
    assert "private-payment-value" not in response.text + caplog.text
    analyzer.assert_not_called()


@pytest.mark.parametrize("exception,status,code", [
    (service.SalePhotoError("secret OCR response"), 503, "service_unavailable"),
    (service.SalePhotoTimeout("secret timeout data"), 504, "timeout"),
])
def test_provider_errors_are_traced(api, exception, status, code, caplog):
    client, analyzer, _, _ = api
    analyzer.side_effect = exception
    response = extract(client)
    check_error(response, status, code)
    assert REQUEST_ID in caplog.text
    assert type(exception).__name__ in caplog.text
    assert str(exception) not in caplog.text + response.text


def test_unexpected_server_exception_is_logged_and_propagated(api, caplog):
    client, analyzer, _, _ = api
    analyzer.side_effect = RuntimeError("secret internal database value")
    with pytest.raises(RuntimeError, match="secret internal database value"):
        extract(client)
    assert REQUEST_ID in caplog.text
    assert "RuntimeError" in caplog.text
    assert "secret internal database value" not in caplog.text


def test_invalid_request_id_is_replaced(api, caplog):
    client, _, _, _ = api
    response = client.post(
        "/pwa/sales/photo/confirm",
        json={},
        headers={"X-Request-ID": "secret-user-controlled-id"},
    )
    request_id = response.headers["x-request-id"]
    assert str(UUID(request_id)) == request_id
    assert response.json()["error"]["request_id"] == request_id
    assert "secret-user-controlled-id" not in response.text + caplog.text


def test_service_does_not_wrap_programming_errors(monkeypatch):
    from app.services import expense_scan_service
    client = Mock()
    client.chat.completions.create.side_effect = RuntimeError("programming bug")
    monkeypatch.setattr(expense_scan_service, "_get_client", lambda: client)
    with pytest.raises(RuntimeError, match="programming bug"):
        service.analyze_sale_photo(JPEG, "image/jpeg")


def test_service_classifies_provider_timeout(monkeypatch):
    import httpx
    from openai import APITimeoutError
    from app.services import expense_scan_service
    client = Mock()
    client.chat.completions.create.side_effect = APITimeoutError(
        request=httpx.Request("POST", "https://example.invalid")
    )
    monkeypatch.setattr(expense_scan_service, "_get_client", lambda: client)
    with pytest.raises(service.SalePhotoTimeout):
        service.analyze_sale_photo(JPEG, "image/jpeg")
