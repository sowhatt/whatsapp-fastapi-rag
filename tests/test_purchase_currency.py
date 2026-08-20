from decimal import Decimal

from app.services import message_orchestrator


def test_format_money_ngn():
    assert (
        message_orchestrator.format_money(500000, "NGN")
        == "500 000 NGN"
    )


def test_purchase_summary_keeps_original_currency():
    action = {
        "type": "purchase",
        "quantity": 20,
        "unit": "Carton",
        "product": "Tomates",
        "supplier": "Chinedu",
        "amount": 195000,
        "payment": "cash",
        "original_amount": 500000,
        "original_currency": "NGN",
        "exchange_rate": "0.39",
        "_currency_converted": True,
    }

    text = message_orchestrator.build_operation_summary(
        action,
        confirm=True,
    )

    assert "500 000 NGN" in text
    assert "195 000 FCFA" in text
    assert "1 NGN = 0.390000 XOF" in text


def test_prepare_purchase_currency_converts_once(monkeypatch):
    calls = []

    monkeypatch.setattr(
        message_orchestrator,
        "seed_currencies",
        lambda db: None,
    )

    def fake_convert_currency(*, amount, from_code, to_code, db):
        calls.append((amount, from_code, to_code))
        return Decimal("195000"), Decimal("0.39")

    monkeypatch.setattr(
        message_orchestrator,
        "convert_currency",
        fake_convert_currency,
    )

    action = {
        "type": "purchase",
        "amount": 500000,
        "currency": "NGN",
    }

    message_orchestrator._prepare_purchase_currency(
        action,
        object(),
    )

    assert action["original_amount"] == 500000
    assert action["original_currency"] == "NGN"
    assert action["amount"] == 195000
    assert action["amount_xof"] == 195000
    assert action["exchange_rate"] == "0.39"
    assert len(calls) == 1

    # deuxième passage du workflow : aucune reconversion
    message_orchestrator._prepare_purchase_currency(
        action,
        object(),
    )

    assert len(calls) == 1


def test_xof_purchase_is_unchanged():
    action = {
        "type": "purchase",
        "amount": 500000,
        "currency": "XOF",
    }

    message_orchestrator._prepare_purchase_currency(
        action,
        object(),
    )

    assert action["amount"] == 500000
    assert action["original_amount"] == 500000
    assert action["original_currency"] == "XOF"
    assert action["exchange_rate"] == "1"
