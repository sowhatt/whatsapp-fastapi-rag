from decimal import Decimal
from types import SimpleNamespace

import jwt
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.routers import pwa_finance


TEST_SECRET = "test-finance-http-secret-" + ("x" * 32)


class FakeInfoSession:
    def __init__(self):
        self.info = {}


def _overview():
    return SimpleNamespace(
        sales_total=Decimal("51000"),
        sales_paid=Decimal("49000"),
        customer_credit_generated=Decimal("2000"),
        cogs=Decimal("30000"),
        gross_margin=Decimal("21000"),
        gross_margin_rate=Decimal("41.18"),

        purchases_total=Decimal("40000"),
        purchases_paid=Decimal("0"),
        supplier_credit_generated=Decimal("40000"),
        expenses_total=Decimal("5000"),
        net_cash_flow=Decimal("4000"),

        customer_receivables=Decimal("2000"),
        overdue_receivables=Decimal("0"),
        supplier_payables=Decimal("40000"),

        stock_value=Decimal("100000"),
        potential_sales_value=Decimal("150000"),

        estimated_current_assets=Decimal("102000"),
        estimated_current_liabilities=Decimal("40000"),
        estimated_net_position=Decimal("62000"),
    )


def _token(
    *,
    merchant_id: int,
    shop_id: int,
    role: str,
):
    import time

    now = int(time.time())

    return jwt.encode(
        {
            "sub": str(merchant_id),
            "merchant_id": merchant_id,
            "shop_id": shop_id,
            "role": role,
            "iat": now,
            "exp": now + 3600,
            "type": "access",
        },
        TEST_SECRET,
        algorithm="HS256",
    )


def test_finance_uses_shop_from_authenticated_token(
    monkeypatch,
):
    monkeypatch.setenv(
        "PWA_JWT_SECRET",
        TEST_SECRET,
    )

    db = FakeInfoSession()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    captured = []

    def fake_overview(
        merchant_id,
        db,
        shop_id=None,
        since=None,
        until=None,
    ):
        captured.append(
            {
                "merchant_id": merchant_id,
                "shop_id": shop_id,
                "since": since,
                "until": until,
            }
        )
        return _overview()

    monkeypatch.setattr(
        pwa_finance,
        "get_financial_overview",
        fake_overview,
    )

    #
    # require_pwa_merchant effect is tested elsewhere.
    # Here we validate that Finance consumes the
    # authenticated shop context, never a client shop_id.
    #
    def run_for_shop(shop_id: int, role: str):
        db.info.clear()
        db.info.update(
            {
                "merchant_id": 1,
                "pwa_shop_id": shop_id,
                "pwa_role": role,
            }
        )

        return pwa_finance.finance_overview(
            period="month",
            db=db,
        )

    try:
        shop_a = run_for_shop(
            shop_id=10,
            role="SELLER",
        )

        shop_b = run_for_shop(
            shop_id=20,
            role="MANAGER",
        )
    finally:
        app.dependency_overrides.clear()

    assert shop_a["merchant_id"] == 1
    assert shop_a["shop_id"] == 10

    assert shop_b["merchant_id"] == 1
    assert shop_b["shop_id"] == 20

    assert captured[0]["merchant_id"] == 1
    assert captured[0]["shop_id"] == 10

    assert captured[1]["merchant_id"] == 1
    assert captured[1]["shop_id"] == 20


def test_finance_endpoint_rejects_missing_jwt(
    monkeypatch,
):
    monkeypatch.setenv(
        "PWA_JWT_SECRET",
        TEST_SECRET,
    )

    client = TestClient(app)

    response = client.get(
        "/pwa/finance/overview?period=month"
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentification requise"
    }


def test_finance_router_exposes_no_shop_id_parameter():
    import inspect

    signature = inspect.signature(
        pwa_finance.finance_overview
    )

    assert "shop_id" not in signature.parameters
