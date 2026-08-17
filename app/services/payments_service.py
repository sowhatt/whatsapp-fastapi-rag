from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.sale import Sale
from app.schemas.payment import PaymentCreate


class PaymentServiceError(Exception):
    pass


@dataclass
class ResolvedPayment:
    customer: Customer
    sale: Sale
    amount: int
    channel: str

    @property
    def remaining_before(self) -> int:
        return int(self.sale.remaining_amount or 0)

    @property
    def remaining_after(self) -> int:
        return max(0, self.remaining_before - self.amount)


def normalize_channel(value: str) -> str:
    lower = value.lower()
    if "moov" in lower:
        return "moov_money"
    if "mtn" in lower:
        return "mtn_momo"
    return "cash"


def find_customer_by_name(name: str, db: Session) -> Customer:
    from app.services.text_normalize import find_customer_accent_insensitive

    customer = find_customer_accent_insensitive(name, db)
    if not customer:
        raise PaymentServiceError(f"Client introuvable : {name}")
    return customer


def find_open_sale_for_customer(customer_id: int, db: Session) -> Sale:
    sale = (
        db.query(Sale)
        .filter(
            Sale.customer_id == customer_id,
            Sale.remaining_amount > 0,
            Sale.status != "cancelled",
        )
        .order_by(Sale.id.asc())
        .first()
    )

    if not sale:
        raise PaymentServiceError("Aucune vente ouverte trouvée pour ce client")

    return sale


def resolve_payment_intent(intent: dict[str, Any], db: Session) -> ResolvedPayment:
    if intent.get("type") != "payment":
        raise PaymentServiceError("L'intention fournie n'est pas un paiement client.")

    amount = int(intent.get("amount", 0))
    if amount <= 0:
        raise PaymentServiceError("Montant invalide.")

    customer = find_customer_by_name(str(intent["customer"]), db)
    sale = find_open_sale_for_customer(customer.id, db)

    if amount > int(sale.remaining_amount or 0):
        raise PaymentServiceError(
            f"Le montant {amount} dépasse le reste dû {int(sale.remaining_amount or 0)}"
        )

    return ResolvedPayment(
        customer=customer,
        sale=sale,
        amount=amount,
        channel="cash",
    )


def build_payment_create_payload(resolved: ResolvedPayment) -> PaymentCreate:
    return PaymentCreate(
        sale_id=resolved.sale.id,
        customer_id=resolved.customer.id,
        amount=resolved.amount,
        channel=resolved.channel,
        reference=None,
    )


def create_payment_from_intent(
    intent: dict[str, Any],
    db: Session,
    create_payment_func: Callable[[PaymentCreate, Session], Any],
) -> Any:
    resolved = resolve_payment_intent(intent, db)
    payload = build_payment_create_payload(resolved)
    return create_payment_func(payload, db)


def preview_payment_from_intent(intent: dict[str, Any], db: Session) -> dict[str, Any]:
    resolved = resolve_payment_intent(intent, db)

    return {
        "customer_id": resolved.customer.id,
        "customer_name": resolved.customer.name,
        "sale_id": resolved.sale.id,
        "amount": resolved.amount,
        "channel": resolved.channel,
        "remaining_before": resolved.remaining_before,
        "remaining_after": resolved.remaining_after,
    }