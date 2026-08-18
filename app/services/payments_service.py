from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.sale import Sale
from app.schemas.payment import PaymentCreate


class PaymentServiceError(Exception):
    pass


@dataclass
class ResolvedPayment:
    """
    Un paiement client peut désormais se répartir sur PLUSIEURS ventes
    ouvertes (les plus anciennes d'abord), pas seulement une seule —
    sinon "Awa paye 100000" échouait dès que ce montant dépassait la
    plus ancienne vente impayée, même si la dette TOTALE d'Awa (somme
    de toutes ses ventes ouvertes) suffisait largement à couvrir.
    """

    customer: Customer
    allocations: list[tuple[Sale, int]]
    amount: int
    channel: str

    @property
    def remaining_before(self) -> int:
        return sum(int(sale.remaining_amount or 0) for sale, _ in self.allocations)

    @property
    def remaining_after(self) -> int:
        return max(0, self.remaining_before - self.amount)


def normalize_channel(value: str) -> str:
    lower = value.lower()
    if "moov" in lower:
        return "moov_money"
    if "mtn" in lower:
        return "mtn_momo"
    if "orange" in lower:
        return "orange_money"
    if "wave" in lower:
        return "wave"
    return "cash"


def find_customer_by_name(name: str, db: Session) -> Customer:
    from app.services.text_normalize import find_customer_accent_insensitive

    customer = find_customer_accent_insensitive(name, db)
    if not customer:
        raise PaymentServiceError(f"Client introuvable : {name}")
    return customer


def find_open_sales_for_customer(customer_id: int, db: Session) -> list[Sale]:
    """
    Toutes les ventes encore partiellement ou totalement impayées de
    ce client, des plus anciennes aux plus récentes — un paiement
    global s'impute d'abord sur les plus anciennes (comme le ferait
    un commerçant qui règle ses dettes dans l'ordre).
    """
    return (
        db.query(Sale)
        .filter(
            Sale.customer_id == customer_id,
            Sale.remaining_amount > 0,
            Sale.status != "cancelled",
        )
        .order_by(Sale.id.asc())
        .all()
    )


def resolve_payment_intent(intent: dict[str, Any], db: Session) -> ResolvedPayment:
    if intent.get("type") != "payment":
        raise PaymentServiceError("L'intention fournie n'est pas un paiement client.")

    amount = int(intent.get("amount", 0))
    if amount <= 0:
        raise PaymentServiceError("Montant invalide.")

    customer = find_customer_by_name(str(intent["customer"]), db)
    open_sales = find_open_sales_for_customer(customer.id, db)

    if not open_sales:
        raise PaymentServiceError("Aucune vente ouverte trouvée pour ce client")

    total_remaining = sum(int(sale.remaining_amount or 0) for sale in open_sales)
    if amount > total_remaining:
        raise PaymentServiceError(
            f"Le montant {amount} dépasse le reste dû total {total_remaining}"
        )

    allocations: list[tuple[Sale, int]] = []
    montant_a_repartir = amount
    for sale in open_sales:
        if montant_a_repartir <= 0:
            break
        part = min(montant_a_repartir, int(sale.remaining_amount or 0))
        if part > 0:
            allocations.append((sale, part))
            montant_a_repartir -= part

    return ResolvedPayment(
        customer=customer,
        allocations=allocations,
        amount=amount,
        channel="cash",
    )


def build_payment_create_payloads(resolved: ResolvedPayment) -> list[PaymentCreate]:
    return [
        PaymentCreate(
            sale_id=sale.id,
            customer_id=resolved.customer.id,
            amount=part,
            channel=resolved.channel,
            reference=None,
        )
        for sale, part in resolved.allocations
    ]


@dataclass
class _PaymentBatchResult:
    """
    Résultat regroupé quand un paiement s'est réparti sur plusieurs
    ventes : .amount reste le montant TOTAL payé (comme un vrai objet
    Payment unique), pour que le message de confirmation affiche le
    bon total plutôt que juste la dernière part imputée.
    """

    amount: int
    sale_ids: list[int] = field(default_factory=list)


def create_payment_from_intent(
    intent: dict[str, Any],
    db: Session,
    create_payment_func: Callable[[PaymentCreate, Session], Any],
) -> Any:
    resolved = resolve_payment_intent(intent, db)
    payloads = build_payment_create_payloads(resolved)

    if len(payloads) == 1:
        return create_payment_func(payloads[0], db)

    sale_ids = []
    for payload in payloads:
        item = create_payment_func(payload, db)
        sale_ids.append(item.sale_id)
    return _PaymentBatchResult(amount=resolved.amount, sale_ids=sale_ids)


def preview_payment_from_intent(intent: dict[str, Any], db: Session) -> dict[str, Any]:
    resolved = resolve_payment_intent(intent, db)

    return {
        "customer_id": resolved.customer.id,
        "customer_name": resolved.customer.name,
        "sale_ids": [sale.id for sale, _ in resolved.allocations],
        "amount": resolved.amount,
        "channel": resolved.channel,
        "remaining_before": resolved.remaining_before,
        "remaining_after": resolved.remaining_after,
    }
