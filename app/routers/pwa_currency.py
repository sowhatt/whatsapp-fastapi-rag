from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate
from app.models.shop import Shop
from app.services.shop_context_service import get_current_shop_id

router = APIRouter(tags=["pwa currencies"])

FRANKFURTER_BASE = "https://api.frankfurter.dev/v2"
DEFAULT_CODES = ("EUR", "XOF", "USD", "NGN", "GHS", "GBP")


class ShopCurrencyUpdate(BaseModel):
    currency_code: str = Field(min_length=3, max_length=3)


class CurrencyConvertRequest(BaseModel):
    amount: Decimal
    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str | None = Field(default=None, min_length=3, max_length=3)


class CurrencyBatchItem(BaseModel):
    index: int = Field(ge=0)
    amount: Decimal
    from_currency: str = Field(min_length=3, max_length=3)


class CurrencyBatchConvertRequest(BaseModel):
    items: list[CurrencyBatchItem]
    to_currency: str | None = Field(default=None, min_length=3, max_length=3)


def _current_shop(db: Session) -> Shop:
    shop_id = get_current_shop_id(db)
    if shop_id is None:
        raise HTTPException(status_code=409, detail="Sélectionne d'abord une boutique.")

    shop = db.query(Shop).filter(Shop.id == shop_id, Shop.is_active.is_(True)).first()
    if shop is None:
        raise HTTPException(status_code=409, detail="Boutique active introuvable.")
    return shop


def _currency(db: Session, code: str) -> Currency:
    normalized = str(code or "").upper().strip()
    currency = db.query(Currency).filter(Currency.code == normalized, Currency.is_active.is_(True)).first()
    if currency is None:
        raise HTTPException(status_code=422, detail=f"Devise non prise en charge : {normalized}")
    return currency


def _frankfurter_rate(base: str, quote: str) -> tuple[Decimal, str]:
    if base == quote:
        return Decimal("1"), datetime.now(timezone.utc).date().isoformat()

    try:
        response = requests.get(
            f"{FRANKFURTER_BASE}/rate/{base.lower()}/{quote.lower()}",
            timeout=8,
            headers={"User-Agent": "Whatzabi-Currency/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        return Decimal(str(payload["rate"])), str(payload["date"])
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Service de taux de change temporairement indisponible.",
        ) from exc


def _save_rate(
    db: Session,
    *,
    base: Currency,
    quote: Currency,
    rate: Decimal,
    valid_date: str,
) -> None:
    valid_at = datetime.fromisoformat(valid_date).replace(tzinfo=None)
    existing = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.base_currency_id == base.id,
            ExchangeRate.quote_currency_id == quote.id,
            ExchangeRate.valid_at == valid_at,
            ExchangeRate.source == "frankfurter",
        )
        .first()
    )
    if existing is None:
        db.add(
            ExchangeRate(
                base_currency_id=base.id,
                quote_currency_id=quote.id,
                rate=rate,
                source="frankfurter",
                retrieved_at=datetime.utcnow(),
                valid_at=valid_at,
            )
        )
    else:
        existing.rate = rate
        existing.retrieved_at = datetime.utcnow()


def _convert_amount(amount: Decimal, rate: Decimal, decimals: int) -> Decimal:
    quant = Decimal("1") if decimals <= 0 else Decimal("1").scaleb(-decimals)
    return (amount * rate).quantize(quant, rounding=ROUND_HALF_UP)


@router.get("/currencies/context")
def currency_context(db: Session = Depends(get_db)):
    shop = _current_shop(db)
    currencies = (
        db.query(Currency)
        .filter(Currency.is_active.is_(True))
        .order_by(Currency.code.asc())
        .all()
    )

    return {
        "shop_currency": shop.currency_code,
        "currencies": [
            {
                "code": item.code,
                "name": item.name,
                "symbol": item.symbol,
                "decimals": item.decimals,
            }
            for item in currencies
        ],
    }


@router.put("/currencies/shop")
def update_shop_currency(payload: ShopCurrencyUpdate, db: Session = Depends(get_db)):
    shop = _current_shop(db)
    role = db.info.get("pwa_role")
    if role not in {"OWNER", "MANAGER"}:
        raise HTTPException(
            status_code=403,
            detail="Seul le propriétaire ou le manager peut changer la devise de la boutique.",
        )

    currency = _currency(db, payload.currency_code)
    shop.currency_code = currency.code
    db.commit()

    return {
        "shop_id": shop.id,
        "currency_code": currency.code,
        "symbol": currency.symbol,
        "decimals": currency.decimals,
    }


@router.get("/currencies/rates")
def list_rates(base: str = "EUR", db: Session = Depends(get_db)):
    base_currency = _currency(db, base)
    rows = []

    for code in DEFAULT_CODES:
        if code == base_currency.code:
            continue

        quote = db.query(Currency).filter(Currency.code == code, Currency.is_active.is_(True)).first()
        if quote is None:
            continue

        rate, valid_date = _frankfurter_rate(base_currency.code, quote.code)
        _save_rate(
            db,
            base=base_currency,
            quote=quote,
            rate=rate,
            valid_date=valid_date,
        )
        rows.append(
            {
                "base": base_currency.code,
                "quote": quote.code,
                "rate": str(rate),
                "date": valid_date,
                "source": "Frankfurter",
            }
        )

    db.commit()
    return rows


@router.post("/currencies/convert")
def convert_currency(payload: CurrencyConvertRequest, db: Session = Depends(get_db)):
    shop = _current_shop(db)
    base = _currency(db, payload.from_currency)
    quote = _currency(db, payload.to_currency or shop.currency_code)

    rate, valid_date = _frankfurter_rate(base.code, quote.code)
    converted = _convert_amount(payload.amount, rate, quote.decimals)

    _save_rate(
        db,
        base=base,
        quote=quote,
        rate=rate,
        valid_date=valid_date,
    )
    db.commit()

    return {
        "amount": str(payload.amount),
        "from_currency": base.code,
        "to_currency": quote.code,
        "rate": str(rate),
        "converted_amount": str(converted),
        "rate_date": valid_date,
        "source": "Frankfurter",
    }


@router.post("/currencies/convert-batch")
def convert_currency_batch(
    payload: CurrencyBatchConvertRequest,
    db: Session = Depends(get_db),
):
    shop = _current_shop(db)
    quote = _currency(db, payload.to_currency or shop.currency_code)

    if not payload.items:
        return {
            "to_currency": quote.code,
            "items": [],
            "rates": [],
        }

    grouped: dict[str, list[CurrencyBatchItem]] = {}
    for item in payload.items:
        code = str(item.from_currency or "").upper().strip()
        grouped.setdefault(code, []).append(item)

    converted_items = []
    rate_rows = []

    for code, items in grouped.items():
        base = _currency(db, code)
        rate, valid_date = _frankfurter_rate(base.code, quote.code)

        _save_rate(
            db,
            base=base,
            quote=quote,
            rate=rate,
            valid_date=valid_date,
        )

        rate_rows.append(
            {
                "from_currency": base.code,
                "to_currency": quote.code,
                "rate": str(rate),
                "rate_date": valid_date,
                "source": "Frankfurter",
            }
        )

        for item in items:
            converted_items.append(
                {
                    "index": item.index,
                    "amount": str(item.amount),
                    "from_currency": base.code,
                    "to_currency": quote.code,
                    "rate": str(rate),
                    "converted_amount": str(
                        _convert_amount(item.amount, rate, quote.decimals)
                    ),
                    "rate_date": valid_date,
                    "source": "Frankfurter",
                }
            )

    db.commit()

    converted_items.sort(key=lambda item: item["index"])
    return {
        "to_currency": quote.code,
        "items": converted_items,
        "rates": rate_rows,
    }
