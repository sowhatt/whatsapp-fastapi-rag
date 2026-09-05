import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.rbac import has_permission, require_permission


def _db_with_staff(role: str | None) -> Session:
    db = Session()
    db.info["pwa_user_id"] = 123
    db.info["pwa_role"] = role
    return db


def test_seller_permissions_match_daily_sales_workflow():
    assert has_permission("SELLER", "product.read")
    assert has_permission("SELLER", "stock.read")
    assert has_permission("SELLER", "customer.read")
    assert has_permission("SELLER", "customer.create")
    assert has_permission("SELLER", "sale.read")
    assert has_permission("SELLER", "sale.create")
    assert not has_permission("SELLER", "product.create")
    assert not has_permission("SELLER", "product.update")
    assert not has_permission("SELLER", "stock.adjust")
    assert not has_permission("SELLER", "sale.cancel")


def test_manager_can_manage_products_stock_and_cancel_sales():
    for permission in (
        "product.read",
        "product.create",
        "product.update",
        "stock.read",
        "stock.adjust",
        "customer.read",
        "customer.create",
        "sale.read",
        "sale.create",
        "sale.cancel",
    ):
        assert has_permission("MANAGER", permission)


def test_stock_manager_cannot_create_sales_or_customers():
    assert has_permission("STOCK_MANAGER", "product.create")
    assert has_permission("STOCK_MANAGER", "product.update")
    assert has_permission("STOCK_MANAGER", "stock.adjust")
    assert not has_permission("STOCK_MANAGER", "sale.create")
    assert not has_permission("STOCK_MANAGER", "customer.create")


def test_accountant_is_read_only_for_core_commercial_operations():
    assert has_permission("ACCOUNTANT", "product.read")
    assert has_permission("ACCOUNTANT", "stock.read")
    assert has_permission("ACCOUNTANT", "customer.read")
    assert has_permission("ACCOUNTANT", "sale.read")
    assert not has_permission("ACCOUNTANT", "product.create")
    assert not has_permission("ACCOUNTANT", "product.update")
    assert not has_permission("ACCOUNTANT", "customer.create")
    assert not has_permission("ACCOUNTANT", "sale.create")
    assert not has_permission("ACCOUNTANT", "sale.cancel")


def test_permission_guard_rejects_forbidden_staff_action():
    db = _db_with_staff("SELLER")
    guard = require_permission("sale.cancel")

    with pytest.raises(HTTPException) as exc:
        guard(db=db)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Permission requise : sale.cancel"


def test_permission_guard_allows_authorized_staff_action():
    db = _db_with_staff("MANAGER")
    guard = require_permission("sale.cancel")

    assert guard(db=db) is None


def test_permission_guard_keeps_internal_and_legacy_flows_compatible():
    db = Session()
    db.info["pwa_role"] = "SELLER"
    guard = require_permission("sale.cancel")

    assert guard(db=db) is None
