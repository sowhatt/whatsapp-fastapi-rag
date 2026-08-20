from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate
from app.services.currency_service import (
    convert_currency_message,
    looks_like_currency_conversion,
    parse_currency_conversion,
    seed_currencies,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session
    session.close()


def add_rate(db, base_code, quote_code, rate):
    seed_currencies(db)

    base = (
        db.query(Currency)
        .filter(Currency.code == base_code)
        .first()
    )

    quote = (
        db.query(Currency)
        .filter(Currency.code == quote_code)
        .first()
    )

    db.add(
        ExchangeRate(
            base_currency_id=base.id,
            quote_currency_id=quote.id,
            rate=Decimal(str(rate)),
            source="test",
            retrieved_at=datetime.now(UTC),
            valid_at=datetime.now(UTC),
        )
    )

    db.commit()


def test_parse_naira_to_cfa():
    parsed = parse_currency_conversion(
        "250000 nairas en CFA"
    )

    assert parsed == (
        Decimal("250000"),
        "NGN",
        "XOF",
    )


def test_parse_cfa_to_naira():
    parsed = parse_currency_conversion(
        "500000 FCFA en nairas"
    )

    assert parsed == (
        Decimal("500000"),
        "XOF",
        "NGN",
    )


def test_parse_euro_to_cfa():
    parsed = parse_currency_conversion(
        "100 euros en CFA"
    )

    assert parsed == (
        Decimal("100"),
        "EUR",
        "XOF",
    )


def test_currency_conversion_detection():
    assert (
        looks_like_currency_conversion(
            "250000 nairas en CFA"
        )
        is True
    )

    assert (
        looks_like_currency_conversion(
            "12500 × 7"
        )
        is False
    )


def test_whatsapp_ngn_to_xof_uses_cached_rate(db):
    add_rate(
        db,
        "NGN",
        "XOF",
        "0.4",
    )

    response = convert_currency_message(
        text="250000 nairas en CFA",
        db=db,
    )

    assert "250 000" in response
    assert "100 000 XOF" in response
    assert "NGN" in response


def test_whatsapp_xof_to_ngn_uses_cached_rate(db):
    add_rate(
        db,
        "XOF",
        "NGN",
        "2.5",
    )

    response = convert_currency_message(
        text="100000 CFA en nairas",
        db=db,
    )

    assert "250 000.00 NGN" in response
