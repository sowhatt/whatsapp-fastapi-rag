from app.agents.intent_agent import detect_explicit_currency


def test_detect_ngn_from_nairas():
    assert (
        detect_explicit_currency(
            "Achat vingt cartons de tomates chez Chinedu "
            "à cinq cent mille nairas"
        )
        == "NGN"
    )


def test_detect_ngn_from_naira():
    assert detect_explicit_currency(
        "J'achète du riz pour 500000 naira"
    ) == "NGN"


def test_detect_ngn_code():
    assert detect_explicit_currency(
        "Achat pour 500000 NGN"
    ) == "NGN"


def test_detect_xof():
    assert detect_explicit_currency(
        "Achat de riz pour 500000 FCFA"
    ) == "XOF"


def test_detect_eur():
    assert detect_explicit_currency(
        "Achat de matériel pour 200 euros"
    ) == "EUR"


def test_detect_usd():
    assert detect_explicit_currency(
        "Achat pour 100 dollars"
    ) == "USD"


def test_no_explicit_currency():
    assert detect_explicit_currency(
        "Achat vingt cartons de tomates pour 500000"
    ) is None


def test_orchestrator_explicit_ngn_overrides_llm_xof():
    from app.services.message_orchestrator import (
        _enforce_explicit_purchase_currency,
    )

    action = {
        "type": "purchase",
        "amount": 500000,
        "currency": "XOF",
    }

    result = _enforce_explicit_purchase_currency(
        action,
        "Achat vingt cartons de tomates chez Chinedu "
        "à cinq cent mille nairas",
    )

    assert result["currency"] == "NGN"


def test_orchestrator_without_currency_keeps_llm_default():
    from app.services.message_orchestrator import (
        _enforce_explicit_purchase_currency,
    )

    action = {
        "type": "purchase",
        "amount": 500000,
        "currency": "XOF",
    }

    result = _enforce_explicit_purchase_currency(
        action,
        "Achat vingt cartons de tomates chez Chinedu pour 500000",
    )

    assert result["currency"] == "XOF"
