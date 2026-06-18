from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.purchase import Purchase
from app.models.supplier import Supplier
from app.schemas.supplier_payment import SupplierPaymentCreate


class SupplierPaymentServiceError(Exception):
    pass


@dataclass
class ResolvedSupplierPayment:
    supplier: Supplier
    purchase: Purchase
    amount: int
    channel: str

    @property
    def remaining_before(self) -> int:
        return int(self.purchase.remaining_amount or 0)

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


def find_supplier_by_name(name: str, db: Session) -> Supplier:
    supplier = db.query(Supplier).filter(Supplier.name.ilike(name)).first()
    if not supplier:
        raise SupplierPaymentServiceError(f"Fournisseur introuvable : {name}")
    return supplier


def find_open_purchase_for_supplier(supplier_id: int, db: Session) -> Purchase:
    purchase = (
        db.query(Purchase)
        .filter(
            Purchase.supplier_id == supplier_id,
            Purchase.remaining_amount > 0,
            Purchase.status != "cancelled",
        )
        .order_by(Purchase.id.asc())
        .first()
    )

    if not purchase:
        raise SupplierPaymentServiceError("Aucun achat ouvert trouvé pour ce fournisseur")

    return purchase


def resolve_supplier_payment_intent(intent: dict[str, Any], db: Session) -> ResolvedSupplierPayment:
    if intent.get("type") != "supplier_payment":
        raise SupplierPaymentServiceError("L'intention fournie n'est pas un paiement fournisseur.")

    amount = int(intent.get("amount", 0))
    if amount <= 0:
        raise SupplierPaymentServiceError("Montant invalide.")

    supplier = find_supplier_by_name(str(intent["supplier"]), db)
    purchase = find_open_purchase_for_supplier(supplier.id, db)

    if amount > int(purchase.remaining_amount or 0):
        raise SupplierPaymentServiceError(
            f"Le montant {amount} dépasse le reste dû {int(purchase.remaining_amount or 0)}"
        )

    channel = normalize_channel(str(intent.get("channel", "cash")))

    return ResolvedSupplierPayment(
        supplier=supplier,
        purchase=purchase,
        amount=amount,
        channel=channel,
    )


def build_supplier_payment_create_payload(
    resolved: ResolvedSupplierPayment,
) -> SupplierPaymentCreate:
    return SupplierPaymentCreate(
        purchase_id=resolved.purchase.id,
        supplier_id=resolved.supplier.id,
        amount=resolved.amount,
        channel=resolved.channel,
        reference=None,
    )


def create_supplier_payment_from_intent(
    intent: dict[str, Any],
    db: Session,
    create_supplier_payment_func: Callable[[SupplierPaymentCreate, Session], Any],
) -> Any:
    resolved = resolve_supplier_payment_intent(intent, db)
    payload = build_supplier_payment_create_payload(resolved)
    return create_supplier_payment_func(payload, db)


def preview_supplier_payment_from_intent(intent: dict[str, Any], db: Session) -> dict[str, Any]:
    resolved = resolve_supplier_payment_intent(intent, db)

    return {
        "supplier_id": resolved.supplier.id,
        "supplier_name": resolved.supplier.name,
        "purchase_id": resolved.purchase.id,
        "amount": resolved.amount,
        "channel": resolved.channel,
        "remaining_before": resolved.remaining_before,
        "remaining_after": resolved.remaining_after,
    }