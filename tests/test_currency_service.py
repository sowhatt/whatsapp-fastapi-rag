from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate
from app.services.currency_service import (
    CurrencyServiceError,
    convert_currency,
    get_exchange_rate,
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


def test_seed_currencies(db):
    seed_currencies(db)

    codes = {
        item.code
        for item in db.query(Currency).all()
    }

    assert {"XOF", "NGN", "EUR", "USD"} <= codes


def test_same_currency_rate_is_one(db):
    seed_currencies(db)

    rate = get_exchange_rate(
        base_code="XOF",
        quote_code="XOF",
        db=db,
    )

    assert rate == Decimal("1")


def test_cached_rate_is_used(db, monkeypatch):
    seed_currencies(db)

    ngn = db.query(Currency).filter(
        Currency.code == "NGN"
    ).first()

    xof = db.query(Currency).filter(
        Currency.code == "XOF"
    ).first()

    db.add(
        ExchangeRate(
            base_currency_id=ngn.id,
            quote_currency_id=xof.id,
            rate=Decimal("0.39000000"),
            source="test",
            retrieved_at=datetime.now(UTC),
            valid_at=datetime.now(UTC),
        )
    )
    db.commit()

    def forbidden_fetch(*args, **kwargs):
        raise AssertionError(
            "L'API externe ne doit pas être appelée."
        )

    monkeypatch.setattr(
        "app.services.currency_service.fetch_rate_from_frankfurter",
        forbidden_fetch,
    )

    rate = get_exchange_rate(
        base_code="NGN",
        quote_code="XOF",
        db=db,
    )

    assert rate == Decimal("0.39000000")


def test_convert_ngn_to_xof_from_cached_rate(db):
    seed_currencies(db)

    ngn = db.query(Currency).filter(
        Currency.code == "NGN"
    ).first()

    xof = db.query(Currency).filter(
        Currency.code == "XOF"
    ).first()

    db.add(
        ExchangeRate(
            base_currency_id=ngn.id,
            quote_currency_id=xof.id,
            rate=Decimal("0.4"),
            source="test",
            retrieved_at=datetime.now(UTC),
            valid_at=datetime.now(UTC),
        )
    )
    db.commit()

    converted, rate = convert_currency(
        amount=Decimal("250000"),
        from_code="NGN",
        to_code="XOF",
        db=db,
    )

    assert rate == Decimal("0.40000000")
    assert converted == Decimal("100000.00000000")


def test_unknown_currency_is_rejected(db):
    seed_currencies(db)

    with pytest.raises(CurrencyServiceError):
        get_exchange_rate(
            base_code="ABC",
            quote_code="XOF",
            db=db,
        )


def test_negative_amount_is_rejected(db):
    seed_currencies(db)

    with pytest.raises(CurrencyServiceError):
        convert_currency(
            amount=Decimal("-1"),
            from_code="NGN",
            to_code="XOF",
            db=db,
        )


def test_old_cached_rate_is_used_if_provider_fails(db, monkeypatch):
    seed_currencies(db)

    from datetime import timedelta

    ngn = db.query(Currency).filter(
        Currency.code == "NGN"
    ).first()

    xof = db.query(Currency).filter(
        Currency.code == "XOF"
    ).first()

    old_rate = ExchangeRate(
        base_currency_id=ngn.id,
        quote_currency_id=xof.id,
        rate=Decimal("0.41862"),
        source="test-old",
        retrieved_at=datetime.now(UTC) - timedelta(days=2),
        valid_at=datetime.now(UTC) - timedelta(days=2),
    )

    db.add(old_rate)
    db.commit()

    def failing_refresh(*args, **kwargs):
        raise CurrencyServiceError("provider down")

    monkeypatch.setattr(
        "app.services.currency_service.refresh_exchange_rate",
        failing_refresh,
    )

    rate = get_exchange_rate(
        base_code="NGN",
        quote_code="XOF",
        db=db,
        max_age_minutes=1,
    )

    assert rate == Decimal("0.41862000")


def test_provider_failure_without_cache_is_raised(db, monkeypatch):
    seed_currencies(db)

    def failing_refresh(*args, **kwargs):
        raise CurrencyServiceError("provider down")

    monkeypatch.setattr(
        "app.services.currency_service.refresh_exchange_rate",
        failing_refresh,
    )

    with pytest.raises(CurrencyServiceError):
        get_exchange_rate(
            base_code="NGN",
            quote_code="XOF",
            db=db,
            max_age_minutes=1,
        )
