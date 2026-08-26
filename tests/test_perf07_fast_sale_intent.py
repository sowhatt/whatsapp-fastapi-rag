from types import SimpleNamespace

import pytest

from app.agents import intent_agent
from app.services import fast_sale_intent_service
from app.services.fast_sale_intent_service import (
    parse_fast_sale_intent,
)


class FakeDB:
    pass


def customer(name="Awa"):
    return SimpleNamespace(name=name)


def product(
    name="Riz",
    unit="Sac",
    price=50_000,
):
    return SimpleNamespace(
        name=name,
        unit=unit,
        price=price,
    )


@pytest.fixture
def known_catalog(monkeypatch):
    monkeypatch.setattr(
        fast_sale_intent_service,
        "find_customer_accent_insensitive",
        lambda name, db: (
            customer("Awa")
            if name.casefold() == "awa"
            else None
        ),
    )
    monkeypatch.setattr(
        fast_sale_intent_service,
        "find_product_candidates",
        lambda name, db: (
            [product()]
            if name.casefold() == "riz"
            else []
        ),
    )


@pytest.mark.parametrize(
    ("spoken", "expected_payment"),
    [
        (
            "Vends deux sacs de riz à Awa.",
            "unknown",
        ),
        (
            "Vends deux sacs de riz à Awa cash.",
            "cash",
        ),
        (
            "J'ai vendu deux sacs de riz à Awa crédit.",
            "credit",
        ),
        (
            "Vente de 2 sacs de riz à Awa Moov.",
            "moov_money",
        ),
    ],
)
def test_fast_sale_accepts_safe_known_sale(
    known_catalog,
    spoken,
    expected_payment,
):
    action = parse_fast_sale_intent(
        spoken,
        FakeDB(),
    )

    assert action is not None
    assert action["type"] == "sale"
    assert action["customer"] == "Awa"
    assert action["product"] == "Riz"
    assert action["unit"] == "Sac"
    assert action["quantity"] == 2
    assert action["amount"] == 100_000
    assert action["payment"] == expected_payment
    assert action["_source"] == "fast_rules"


def test_fast_sale_preserves_explicit_total(
    known_catalog,
):
    action = parse_fast_sale_intent(
        (
            "Vends deux sacs de riz à Awa "
            "pour quatre-vingt mille francs cash."
        ),
        FakeDB(),
    )

    assert action is not None
    assert action["amount"] == 80_000
    assert action["payment"] == "cash"


@pytest.mark.parametrize(
    "spoken",
    [
        "Vends du riz à Awa.",
        "Vends deux sacs de riz.",
        "Vends deux sacs à Awa.",
        "Vends deux sacs de riz à Awar.",
        (
            "Vends deux sacs de riz et trois "
            "cartons de tomates à Awa."
        ),
        (
            "J'ai acheté deux sacs de riz "
            "chez Soglo."
        ),
        "Quels produits ai-je dans mon stock ?",
    ],
)
def test_fast_sale_rejects_uncertain_phrases(
    known_catalog,
    spoken,
):
    assert (
        parse_fast_sale_intent(
            spoken,
            FakeDB(),
        )
        is None
    )


def test_fast_sale_rejects_ambiguous_product(
    monkeypatch,
):
    monkeypatch.setattr(
        fast_sale_intent_service,
        "find_customer_accent_insensitive",
        lambda name, db: customer(),
    )
    monkeypatch.setattr(
        fast_sale_intent_service,
        "find_product_candidates",
        lambda name, db: [
            product("Riz long"),
            product("Riz parfumé"),
        ],
    )

    assert (
        parse_fast_sale_intent(
            "Vends deux sacs de riz à Awa.",
            FakeDB(),
        )
        is None
    )


def test_fast_sale_rejects_wrong_unit(
    known_catalog,
):
    assert (
        parse_fast_sale_intent(
            "Vends deux cartons de riz à Awa.",
            FakeDB(),
        )
        is None
    )


def test_detect_intent_skips_openai_on_fast_sale(
    monkeypatch,
):
    normalization = SimpleNamespace(
        original_text=(
            "Vends deux sacs de riz à Awa."
        ),
        normalized_text=(
            "Vends deux sacs de riz à Awa."
        ),
        corrections=[],
    )
    expected = {
        "type": "sale",
        "product": "Riz",
        "customer": "Awa",
        "quantity": 2,
        "amount": 100_000,
        "payment": "unknown",
        "_source": "fast_rules",
    }

    monkeypatch.setattr(
        intent_agent,
        "normalize_transcription",
        lambda text, db: normalization,
    )
    monkeypatch.setattr(
        intent_agent,
        "parse_fast_sale_intent",
        lambda text, db: dict(expected),
    )

    def forbidden_openai(_text):
        raise AssertionError(
            "OpenAI ne devait pas être appelé"
        )

    monkeypatch.setattr(
        intent_agent,
        "parse_with_ai",
        forbidden_openai,
    )

    action = intent_agent.detect_intent(
        normalization.original_text,
        FakeDB(),
    )

    assert action is not None
    assert action["_source"] == "fast_rules"
    assert action["amount"] == 100_000
    assert action["_original_text"] == (
        normalization.original_text
    )


def test_detect_intent_keeps_ai_fallback(
    monkeypatch,
):
    normalization = SimpleNamespace(
        original_text="Vends du riz.",
        normalized_text="Vends du riz.",
        corrections=[],
    )
    expected = {
        "type": "sale",
        "_source": "ai",
        "_confidence": 0.9,
    }

    monkeypatch.setattr(
        intent_agent,
        "normalize_transcription",
        lambda text, db: normalization,
    )
    monkeypatch.setattr(
        intent_agent,
        "parse_fast_sale_intent",
        lambda text, db: None,
    )
    monkeypatch.setattr(
        intent_agent,
        "parse_with_ai",
        lambda text: dict(expected),
    )

    action = intent_agent.detect_intent(
        normalization.original_text,
        FakeDB(),
    )

    assert action is not None
    assert action["_source"] == "ai"


def test_fast_sale_accepts_whisper_comma_before_payment(
    known_catalog,
):
    action = parse_fast_sale_intent(
        "Vends deux sacs de riz à Awa, cash.",
        FakeDB(),
    )

    assert action is not None
    assert action["customer"] == "Awa"
    assert action["product"] == "Riz"
    assert action["quantity"] == 2
    assert action["amount"] == 100_000
    assert action["payment"] == "cash"
    assert action["_source"] == "fast_rules"
