from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from app.domains.core.internal.transaction_model import BusinessTransaction


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


def update_commerce_transaction(
    *, db: Session, merchant_id: int, transaction_id: int,
    status: TransactionStatus | None = None, payment_status: str | None = None,
) -> None:
    """Update the Core root within the caller's tenant-bound transaction.

    Never commit here: order, stock and outbox must commit or roll back together.
    Preparation and readiness are Online details of a confirmed Core transaction.
    Pending roots from pre-J4.2 orders may catch up; terminal roots cannot regress.
    """
    transaction = (
        db.query(BusinessTransaction)
        .filter(
            BusinessTransaction.id == transaction_id,
            BusinessTransaction.merchant_id == merchant_id,
            BusinessTransaction.kind == TransactionKind.COMMERCE.value,
        )
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if transaction is None:
        raise ValueError("Transaction Core introuvable.")
    if status is not None:
        allowed = {
            "pending": {"pending", "confirmed", "completed", "cancelled"},
            "confirmed": {"confirmed", "completed", "cancelled"},
            "completed": {"completed"},
            "cancelled": {"cancelled"},
        }
        if status.value not in allowed.get(transaction.status, set()):
            raise ValueError("État de transaction Core incompatible.")
        transaction.status = status.value
    if payment_status is not None:
        transaction.payment_status = payment_status
