import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.security import require_admin_token


client = TestClient(app)


def _route_dependencies(path: str, method: str):
    for route in app.routes:
        route_path = getattr(route, "path", None)
        route_methods = getattr(
            route,
            "methods",
            set(),
        )

        if (
            route_path == path
            and method.upper() in route_methods
        ):
            dependant = getattr(
                route,
                "dependant",
                None,
            )

            if dependant is None:
                return []

            return [
                dependency.call
                for dependency
                in dependant.dependencies
            ]

    available_routes = sorted(
        (
            getattr(route, "path", ""),
            sorted(getattr(route, "methods", set())),
        )
        for route in app.routes
        if getattr(route, "path", None)
    )

    raise AssertionError(
        f"Route introuvable : {method} {path}. "
        f"Routes disponibles : {available_routes}"
    )


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/products", "GET"),
        ("/customers", "GET"),
        ("/sales", "GET"),
        ("/financial-entries", "GET"),
        ("/whatsapp/send-test", "POST"),
        ("/debug/env", "GET"),
        ("/admin/truncate-db", "POST"),
    ],
)
def test_internal_routes_require_admin_dependency(
    path,
    method,
):
    dependencies = _route_dependencies(path, method)
    assert require_admin_token in dependencies


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/health", "GET"),
        ("/health/db", "GET"),
        ("/webhooks/whatsapp", "GET"),
        ("/webhooks/whatsapp", "POST"),
    ],
)
def test_required_public_routes_remain_public(
    path,
    method,
):
    dependencies = _route_dependencies(path, method)
    assert require_admin_token not in dependencies


def test_products_reject_request_without_admin_token():
    response = client.get("/products")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Accès refusé",
    }


def test_admin_token_fails_closed_when_not_configured(
    monkeypatch,
):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        require_admin_token("anything")

    assert exc_info.value.status_code == 403


def test_admin_token_accepts_exact_value(monkeypatch):
    monkeypatch.setenv(
        "ADMIN_TOKEN",
        "test-secret-token",
    )

    assert (
        require_admin_token("test-secret-token")
        is None
    )
