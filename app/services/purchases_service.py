from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.supplier import Supplier
from app.schemas.purchase import PurchaseCreate, PurchaseItemCreate


class PurchaseServiceError(Exception):
    pass


@dataclass
class ResolvedPurchase:
    supplier: Supplier
    product: Product
    quantity: int
    total_amount: int
    unit_cost: int
    paid_amount: int
    remaining_amount: int
    payment_channel: str


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
        raise PurchaseServiceError(f"Fournisseur introuvable : {name}")
    return supplier


def find_product_by_name(name: str, db: Session) -> Product:
    product = db.query(Product).filter(Product.name.ilike(name)).first()
    if not product:
        raise PurchaseServiceError(f"Produit introuvable : {name}")
    return product


def resolve_purchase_intent(intent: dict[str, Any], db: Session) -> ResolvedPurchase:
    if intent.get("type") != "purchase":
        raise PurchaseServiceError("L'intention fournie n'est pas un achat.")

    quantity = int(intent.get("quantity", 0))
    total_amount = int(intent.get("amount", 0))

    if quantity <= 0:
        raise PurchaseServiceError("Quantité invalide.")
    if total_amount <= 0:
        raise PurchaseServiceError("Montant invalide.")

    supplier = find_supplier_by_name(str(intent["supplier"]), db)
    product = find_product_by_name(str(intent["product"]), db)

    unit_cost = round(total_amount / quantity)
    paid_amount = 0
    remaining_amount = total_amount
    payment_channel = "cash"

    return ResolvedPurchase(
        supplier=supplier,
        product=product,
        quantity=quantity,
        total_amount=total_amount,
        unit_cost=unit_cost,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_channel=payment_channel,
    )


def build_purchase_create_payload(resolved: ResolvedPurchase) -> PurchaseCreate:
    return PurchaseCreate(
        supplier_id=resolved.supplier.id,
        items=[
            PurchaseItemCreate(
                product_id=resolved.product.id,
                quantity=resolved.quantity,
                unit_cost=resolved.unit_cost,
            )
        ],
        paid_amount=resolved.paid_amount,
        payment_channel=resolved.payment_channel,
    )


def create_purchase_from_intent(
    intent: dict[str, Any],
    db: Session,
    create_purchase_func: Callable[[PurchaseCreate, Session], Any],
) -> Any:
    resolved = resolve_purchase_intent(intent, db)
    payload = build_purchase_create_payload(resolved)
    return create_purchase_func(payload, db)


def preview_purchase_from_intent(intent: dict[str, Any], db: Session) -> dict[str, Any]:
    resolved = resolve_purchase_intent(intent, db)

    return {
        "supplier_id": resolved.supplier.id,
        "supplier_name": resolved.supplier.name,
        "product_id": resolved.product.id,
        "product_name": resolved.product.name,
        "quantity": resolved.quantity,
        "unit_cost": resolved.unit_cost,
        "total_amount": resolved.total_amount,
        "paid_amount": resolved.paid_amount,
        "remaining_amount": resolved.remaining_amount,
        "payment_channel": resolved.payment_channel,
        "stock_before": resolved.product.stock,
        "stock_after": resolved.product.stock + resolved.quantity,
    }