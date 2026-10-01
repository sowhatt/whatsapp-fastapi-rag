from dataclasses import dataclass
from enum import StrEnum


class TransactionKind(StrEnum):
    COMMERCE = "commerce"
    RENTAL = "rental"
    RESTAURANT = "restaurant"
    SERVICE = "service"


class TransactionStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    REFUNDED = "refunded"


@dataclass(frozen=True, slots=True)
class TransactionRef:
    """Stable cross-domain representation of a Whatzabi transaction.

    This contract deliberately contains only fields shared by all verticals.
    Commerce, Rental and Restaurant keep their specific rules and data in
    their own aggregates.
    """

    id: int
    merchant_id: int
    shop_id: int | None
    kind: TransactionKind
    status: TransactionStatus
    currency: str
    subtotal_amount: int
    tax_amount: int
    fee_amount: int
    discount_amount: int
    total_amount: int
    payment_status: PaymentStatus
