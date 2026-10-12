from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import pwa_expenses as expenses
from app.models.merchant_user import MerchantUser  # noqa: F401 — shop_operations foreign key
from app.schemas.expense_scan import ExpenseScanResult
from app.services.expense_scan_service import _normalize_amount
from app.services.currency_service import parse_currency_conversion


@pytest.mark.parametrize("value", ["31,70", "31.70", Decimal("31.70")])
def test_source_amount_preserves_decimals(value):
    payload = expenses.ExpenseCreateRequest(entry_type="expense", amount=value, label="Ticket")
    assert payload.amount == Decimal("31.70")
    assert _normalize_amount(value) == Decimal("31.70")
    assert ExpenseScanResult(amount=_normalize_amount(value)).amount == Decimal("31.70")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-31.70", "0", "1,234.56", "31..70"])
def test_invalid_source_amount_rejected(value):
    with pytest.raises(ValidationError):
        expenses.ExpenseCreateRequest(entry_type="expense", amount=value, label="Ticket")
    assert _normalize_amount(value) is None


@pytest.mark.parametrize("alias", ["CNY", "RMB", "yuan", "yuans", "renminbi"])
def test_yuan_conversion_aliases(alias):
    assert parse_currency_conversion(f"31,70 {alias} en CFA") == (Decimal("31.70"), "CNY", "XOF")


@pytest.fixture
def conversion(monkeypatch):
    saved = []
    monkeypatch.setattr(expenses, "_current_shop", lambda db: SimpleNamespace(currency_code="XOF"))
    monkeypatch.setattr(expenses, "_currency", lambda db, code: SimpleNamespace(code=code, decimals=0 if code == "XOF" else 2))
    def rate(base, quote):
        return Decimal({"EUR": "655.957", "CNY": "80.25", "XOF": "1"}[base]), "2026-10-12"
    monkeypatch.setattr(expenses, "_frankfurter_rate", rate)
    monkeypatch.setattr(expenses, "_save_rate", lambda *args, **kwargs: saved.append(kwargs))
    return saved


@pytest.mark.parametrize("source,amount,expected", [("EUR", "31,70", 20794), ("CNY", "100.50", 8065)])
def test_expense_converted_on_server(conversion, source, amount, expected):
    request = expenses.ExpenseCreateRequest(entry_type="expense", amount=amount, source_currency=source,
        expected_amount=expected, label="Ticket", note="Achat fournisseur")
    payload = expenses._expense_payload(request, object())
    assert payload.amount == expected
    assert f"{request.amount} {source} -> {expected} XOF" in payload.note
    assert "date=2026-10-12" in payload.note
    assert "Achat fournisseur" in payload.note
    assert len(conversion) == 1


def test_changed_or_forged_conversion_is_rejected(conversion):
    request = expenses.ExpenseCreateRequest(entry_type="expense", amount="31.70", source_currency="EUR",
        expected_amount=3170, label="Ticket")
    with pytest.raises(HTTPException) as exc:
        expenses._expense_payload(request, object())
    assert exc.value.status_code == 409
    assert conversion == []


def test_foreign_expense_requires_conversion_confirmation(conversion):
    request = expenses.ExpenseCreateRequest(entry_type="expense", amount="31.70", source_currency="EUR", label="Ticket")
    with pytest.raises(HTTPException) as exc:
        expenses._expense_payload(request, object())
    assert exc.value.status_code == 422


def test_local_legacy_expense_is_unchanged(conversion):
    request = expenses.ExpenseCreateRequest(entry_type="expense", amount=5000, label="Transport")
    payload = expenses._expense_payload(request, object())
    assert payload.amount == 5000
    assert payload.note is None
    assert conversion == []


def test_rate_unavailable_does_not_create_payload(conversion, monkeypatch):
    def unavailable(*args):
        raise HTTPException(status_code=503, detail="Taux indisponible")
    monkeypatch.setattr(expenses, "_frankfurter_rate", unavailable)
    request = expenses.ExpenseCreateRequest(entry_type="expense", amount="31.70", source_currency="EUR", expected_amount=20794, label="Ticket")
    with pytest.raises(HTTPException) as exc:
        expenses._expense_payload(request, object())
    assert exc.value.status_code == 503
    assert conversion == []


def test_converted_expense_persists_to_ledger_and_shop(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.db.tenant import set_current_merchant
    from app.models.merchant import Merchant
    from app.models.shop import Shop
    from app.models.financial_entry import FinancialEntry
    from app.models.shop_operation import ShopOperation
    from app.models.transaction_event import TransactionEvent
    from app.services.currency_service import seed_currencies
    from app.routers.pwa_currency import currency_context

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        merchant = Merchant(whatsapp_number="expense-currency-test")
        db.add(merchant)
        db.flush()
        shop = Shop(merchant_id=merchant.id, name="Boutique", code="TEST", currency_code="XOF")
        db.add(shop)
        db.commit()
        set_current_merchant(db, merchant.id)
        db.info.update(pwa_shop_id=shop.id, pwa_role="OWNER")
        seed_currencies(db)
        assert "CNY" in {row["code"] for row in currency_context(db)["currencies"]}
        monkeypatch.setattr(expenses, "_frankfurter_rate", lambda *args: (Decimal("655.957"), "2026-10-12"))
        monkeypatch.setattr(expenses, "refresh_shop_analytics", lambda db: None)
        request = expenses.ExpenseCreateRequest(entry_type="expense", amount="31,70", source_currency="EUR",
            expected_amount=20794, label="Ticket européen")
        result = expenses.create_expense(request, db)
        assert result["amount"] == 20794
        assert db.query(FinancialEntry).one().amount == 20794
        assert db.query(TransactionEvent).one().amount_signed == -20794
        assert db.query(ShopOperation).one().shop_id == shop.id
        assert "31.70 EUR" in result["note"]
