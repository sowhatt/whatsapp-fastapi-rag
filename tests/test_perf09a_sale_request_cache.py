from pathlib import Path

import pytest

from app.services.sales_service import (
    create_sale_from_intent,
)


class Entity:
    def __init__(self, entity_id):
        self.id = entity_id


class Resolved:
    def __init__(self):
        self.customer = Entity(10)
        product = Entity(20)
        self.lines = [
            type(
                "Line",
                (),
                {"product": product},
            )(),
        ]


class FakeDB:
    def __init__(self):
        self.info = {}


def install_mocks(monkeypatch, resolved):
    from app.services import sales_service

    monkeypatch.setattr(
        sales_service,
        "resolve_sale_intent",
        lambda intent, session: resolved,
    )
    monkeypatch.setattr(
        sales_service,
        "build_sale_create_payload",
        lambda value: "payload",
    )


def test_cache_is_available_and_then_cleared(
    monkeypatch,
):
    db = FakeDB()
    resolved = Resolved()
    observed = {}

    install_mocks(monkeypatch, resolved)

    def fake_create(payload, session):
        observed["customer"] = session.info[
            "_whatzabi_resolved_sale_customer"
        ]
        observed["products"] = session.info[
            "_whatzabi_resolved_sale_products"
        ]
        return "created"

    result = create_sale_from_intent(
        {"type": "sale"},
        db,
        fake_create,
    )

    assert result == "created"
    assert observed["customer"] is resolved.customer
    assert observed["products"][20] is (
        resolved.lines[0].product
    )
    assert db.info == {}


def test_cache_is_cleared_on_failure(
    monkeypatch,
):
    db = FakeDB()
    resolved = Resolved()

    install_mocks(monkeypatch, resolved)

    def failing_create(payload, session):
        raise RuntimeError("failure")

    with pytest.raises(
        RuntimeError,
        match="failure",
    ):
        create_sale_from_intent(
            {"type": "sale"},
            db,
            failing_create,
        )

    assert db.info == {}


def test_router_uses_cache_without_refresh():
    source = Path(
        "app/routers/sales.py"
    ).read_text(encoding="utf-8")

    start = source.index("def create_sale(")
    end = source.index(
        '\n\n@router.get("/sales/{sale_id}/items")',
        start,
    )
    function_source = source[start:end]

    assert (
        '"_whatzabi_resolved_sale_customer"'
        in function_source
    )
    assert (
        '"_whatzabi_resolved_sale_products"'
        in function_source
    )
    assert '"customer_source"' in function_source
    assert (
        "db.expire_on_commit = False"
        in function_source
    )
    assert (
        "\n    db.refresh(sale)\n"
        not in function_source
    )
    assert '"refresh_s"] = 0.0' in function_source
