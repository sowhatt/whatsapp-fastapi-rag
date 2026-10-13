from __future__ import annotations

from enum import StrEnum


class OnlinePaymentMethod(StrEnum):
    CASH_ON_DELIVERY = "cash_on_delivery"
    MOBILE_MONEY = "mobile_money"


class OnlinePaymentStatus(StrEnum):
    UNPAID = "unpaid"
    CASH_ON_DELIVERY = "cash_on_delivery"
    MOBILE_MONEY_PENDING = "mobile_money_pending"
    PAID = "paid"
    FAILED = "failed"


def normalize_payment_method(value: str | OnlinePaymentMethod) -> OnlinePaymentMethod:
    if isinstance(value, OnlinePaymentMethod):
        return value
    try:
        return OnlinePaymentMethod(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError("Mode de paiement Online invalide.") from exc


def initial_payment_status(
    method: str | OnlinePaymentMethod,
) -> OnlinePaymentStatus:
    resolved = normalize_payment_method(method)
    if resolved is OnlinePaymentMethod.CASH_ON_DELIVERY:
        return OnlinePaymentStatus.CASH_ON_DELIVERY
    return OnlinePaymentStatus.MOBILE_MONEY_PENDING
