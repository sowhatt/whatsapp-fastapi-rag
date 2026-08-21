import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.error import URLError
from urllib.request import Request, urlopen

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate


class CurrencyServiceError(ValueError):
    pass


DEFAULT_CURRENCIES = [
    {
        "code": "XOF",
        "name": "Franc CFA BCEAO",
        "symbol": "FCFA",
        "decimals": 0,
    },
    {
        "code": "NGN",
        "name": "Naira nigérian",
        "symbol": "₦",
        "decimals": 2,
    },
    {
        "code": "EUR",
        "name": "Euro",
        "symbol": "€",
        "decimals": 2,
    },
    {
        "code": "USD",
        "name": "Dollar américain",
        "symbol": "$",
        "decimals": 2,
    },
]


def seed_currencies(db: Session) -> None:
    for item in DEFAULT_CURRENCIES:
        existing = (
            db.query(Currency)
            .filter(Currency.code == item["code"])
            .first()
        )

        if existing:
            continue

        db.add(Currency(**item))

    db.commit()


def _get_currency(code: str, db: Session) -> Currency:
    normalized = code.strip().upper()

    currency = (
        db.query(Currency)
        .filter(
            Currency.code == normalized,
            Currency.is_active.is_(True),
        )
        .first()
    )

    if not currency:
        raise CurrencyServiceError(
            f"Devise non supportée : {normalized}"
        )

    return currency


def _latest_rate(
    *,
    base: Currency,
    quote: Currency,
    db: Session,
) -> ExchangeRate | None:
    return (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.base_currency_id == base.id,
            ExchangeRate.quote_currency_id == quote.id,
        )
        .order_by(desc(ExchangeRate.retrieved_at))
        .first()
    )


def fetch_rate_from_frankfurter(
    *,
    base_code: str,
    quote_code: str,
) -> Decimal:
    url = (
        "https://api.frankfurter.dev/v2/rate/"
        f"{base_code.upper()}/{quote_code.upper()}"
    )

    request = Request(
        url,
        headers={
            "User-Agent": "Whatzabi/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )
    except (URLError, TimeoutError, OSError) as exc:
        raise CurrencyServiceError(
            "Impossible de récupérer le taux de change : "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    rate = payload.get("rate")

    if rate is None:
        raise CurrencyServiceError(
            "Le fournisseur de change n'a pas retourné de taux."
        )

    return Decimal(str(rate))


def refresh_exchange_rate(
    *,
    base_code: str,
    quote_code: str,
    db: Session,
) -> ExchangeRate:
    base = _get_currency(base_code, db)
    quote = _get_currency(quote_code, db)

    if base.code == quote.code:
        raise CurrencyServiceError(
            "Les deux devises sont identiques."
        )

    rate = fetch_rate_from_frankfurter(
        base_code=base.code,
        quote_code=quote.code,
    )

    now = datetime.now(UTC)

    exchange_rate = ExchangeRate(
        base_currency_id=base.id,
        quote_currency_id=quote.id,
        rate=rate,
        source="frankfurter",
        retrieved_at=now,
        valid_at=now,
    )

    db.add(exchange_rate)
    db.commit()
    db.refresh(exchange_rate)

    return exchange_rate


def get_exchange_rate(
    *,
    base_code: str,
    quote_code: str,
    db: Session,
    max_age_minutes: int = 720,
) -> Decimal:
    base = _get_currency(base_code, db)
    quote = _get_currency(quote_code, db)

    if base.code == quote.code:
        return Decimal("1")

    latest = _latest_rate(
        base=base,
        quote=quote,
        db=db,
    )

    if latest:
        retrieved_at = latest.retrieved_at

        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=UTC)

        age = datetime.now(UTC) - retrieved_at

        if age <= timedelta(minutes=max_age_minutes):
            return Decimal(str(latest.rate))

    try:
        refreshed = refresh_exchange_rate(
            base_code=base.code,
            quote_code=quote.code,
            db=db,
        )

        return Decimal(str(refreshed.rate))

    except CurrencyServiceError:
        # Si l'API externe tombe mais qu'un ancien taux existe,
        # Whatzabi continue avec le dernier taux connu.
        if latest is not None:
            return Decimal(str(latest.rate))

        raise


def convert_currency(
    *,
    amount: Decimal,
    from_code: str,
    to_code: str,
    db: Session,
) -> tuple[Decimal, Decimal]:
    if amount < 0:
        raise CurrencyServiceError(
            "Le montant ne peut pas être négatif."
        )

    rate = get_exchange_rate(
        base_code=from_code,
        quote_code=to_code,
        db=db,
    )

    converted = amount * rate

    return converted, rate


def format_conversion(
    *,
    amount: Decimal,
    converted: Decimal,
    from_code: str,
    to_code: str,
    rate: Decimal,
) -> str:
    amount_text = f"{amount:,.2f}".replace(",", " ")

    if to_code.upper() == "XOF":
        converted_text = f"{converted:,.0f}".replace(",", " ")
    else:
        converted_text = f"{converted:,.2f}".replace(",", " ")

    return (
        "💱 Conversion\n\n"
        f"{amount_text} {from_code.upper()}\n"
        f"≈ {converted_text} {to_code.upper()}\n\n"
        f"Taux utilisé : "
        f"1 {from_code.upper()} = "
        f"{rate:.6f} {to_code.upper()}"
    )


CURRENCY_ALIASES = {
    "xof": "XOF",
    "cfa": "XOF",
    "fcfa": "XOF",
    "franc cfa": "XOF",
    "francs cfa": "XOF",

    "ngn": "NGN",
    "naira": "NGN",
    "nairas": "NGN",
    "naïra": "NGN",
    "naïras": "NGN",

    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",

    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "dollar américain": "USD",
    "dollars américains": "USD",
}


def _normalize_currency_alias(value: str) -> str | None:
    normalized = " ".join(
        value.lower()
        .replace("’", "'")
        .split()
    ).strip(" .!?")

    return CURRENCY_ALIASES.get(normalized)


def looks_like_currency_conversion(text: str) -> bool:
    normalized = " ".join(text.lower().split())

    currency_words = (
        "naira",
        "nairas",
        "ngn",
        "cfa",
        "fcfa",
        "xof",
        "euro",
        "euros",
        "eur",
        "dollar",
        "dollars",
        "usd",
    )

    has_currency = any(
        word in normalized
        for word in currency_words
    )

    has_conversion_marker = bool(
        re.search(
            r"\b(en|vers|convertis?|convertir|ça fait combien|"
            r"ca fait combien|combien en)\b",
            normalized,
        )
    )

    return has_currency and has_conversion_marker


def parse_currency_conversion(
    text: str,
) -> tuple[Decimal, str, str] | None:
    normalized = " ".join(
        text.lower()
        .replace("’", "'")
        .split()
    ).strip(" .!?")

    patterns = [
        r"^([\d\s]+(?:[,.]\d+)?)\s+"
        r"(.+?)\s+(?:en|vers)\s+(.+)$",

        r"^(?:convertis?|convertir)\s+"
        r"([\d\s]+(?:[,.]\d+)?)\s+"
        r"(.+?)\s+(?:en|vers)\s+(.+)$",

        r"^(?:combien\s+(?:font|fait)|ça\s+fait\s+combien|"
        r"ca\s+fait\s+combien)\s+"
        r"([\d\s]+(?:[,.]\d+)?)\s+"
        r"(.+?)\s+(?:en|vers)\s+(.+)$",
    ]

    for pattern in patterns:
        match = re.match(
            pattern,
            normalized,
            re.IGNORECASE,
        )

        if not match:
            continue

        amount_text = (
            match.group(1)
            .replace(" ", "")
            .replace(",", ".")
        )

        try:
            amount = Decimal(amount_text)
        except Exception:
            return None

        from_code = _normalize_currency_alias(
            match.group(2)
        )

        to_code = _normalize_currency_alias(
            match.group(3)
        )

        if not from_code or not to_code:
            return None

        return amount, from_code, to_code

    return None


def convert_currency_message(
    *,
    text: str,
    db: Session,
) -> str:
    parsed = parse_currency_conversion(text)

    if parsed is None:
        raise CurrencyServiceError(
            "Je n’ai pas reconnu la conversion. "
            "Exemple : 250000 nairas en CFA."
        )

    amount, from_code, to_code = parsed

    seed_currencies(db)

    converted, rate = convert_currency(
        amount=amount,
        from_code=from_code,
        to_code=to_code,
        db=db,
    )

    return format_conversion(
        amount=amount,
        converted=converted,
        from_code=from_code,
        to_code=to_code,
        rate=rate,
    )
