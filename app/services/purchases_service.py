from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.supplier import Supplier
from app.schemas.purchase import PurchaseCreate, PurchaseItemCreate
from app.services.sales_service import _allocate_total, find_product_by_name


class PurchaseServiceError(Exception):
    pass


@dataclass
class ResolvedPurchaseLine:
    product: Product
    quantity: int
    line_total: int


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
    lines: list[ResolvedPurchaseLine] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.lines:
            self.lines = [
                ResolvedPurchaseLine(
                    product=self.product,
                    quantity=self.quantity,
                    line_total=self.total_amount,
                )
            ]


def normalize_channel(value: str) -> str:
    lower = value.lower()
    if "moov" in lower:
        return "moov_money"
    if "mtn" in lower or "momo" in lower:
        return "mtn_momo"
    if "bank" in lower or "banque" in lower or "virement" in lower:
        return "bank"
    if "credit" in lower or "crédit" in lower or "dette" in lower:
        return "credit"
    return "cash"


def find_supplier_by_name(name: str, db: Session) -> Supplier:
    supplier = db.query(Supplier).filter(Supplier.name.ilike(name)).first()
    if not supplier:
        raise PurchaseServiceError(f"Fournisseur introuvable : {name}")
    return supplier


def resolve_purchase_intent(intent: dict[str, Any], db: Session) -> ResolvedPurchase:
    if intent.get("type") != "purchase":
        raise PurchaseServiceError("L'intention fournie n'est pas un achat.")

    quantity = int(intent.get("quantity", 0))
    total_amount = int(intent.get("amount", 0))
    if total_amount <= 0:
        raise PurchaseServiceError("Montant invalide.")

    supplier = find_supplier_by_name(str(intent["supplier"]), db)
    payment_channel = normalize_channel(str(intent.get("payment") or "cash"))

    raw_items = [
        dict(entry)
        for entry in (intent.get("items") or [])
        if entry.get("product")
    ]
    if len(raw_items) > 1:
        resolved_products: list[tuple[Product, int, int | None]] = []
        for entry in raw_items:
            entry_quantity = int(entry.get("quantity") or 0)
            if entry_quantity <= 0:
                raise PurchaseServiceError(
                    f"Quantité invalide pour {entry['product']}."
                )
            entry_product = find_product_by_name(str(entry["product"]), db)
            entry_amount = entry.get("amount")
            resolved_products.append(
                (
                    entry_product,
                    entry_quantity,
                    int(entry_amount) if entry_amount else None,
                )
            )

        item_amounts = [amount for (_, _, amount) in resolved_products]
        if all(amount is not None and amount > 0 for amount in item_amounts):
            line_totals = [int(amount) for amount in item_amounts]
            items_sum = sum(line_totals)
            if total_amount and total_amount != items_sum:
                raise PurchaseServiceError(
                    f"Les montants par produit ({items_sum} FCFA) ne "
                    f"correspondent pas au total annoncé ({total_amount} FCFA)."
                )
            total_amount = items_sum
        else:
            weights = [1 for _ in resolved_products]
            line_totals = _allocate_total(weights, total_amount)

        lines = [
            ResolvedPurchaseLine(
                product=line_product,
                quantity=line_quantity,
                line_total=line_total,
            )
            for (line_product, line_quantity, _), line_total in zip(
                resolved_products, line_totals
            )
        ]
        paid_amount = 0 if payment_channel == "credit" else total_amount
        remaining_amount = total_amount - paid_amount
        return ResolvedPurchase(
            supplier=supplier,
            product=lines[0].product,
            quantity=lines[0].quantity,
            total_amount=total_amount,
            unit_cost=round(lines[0].line_total / lines[0].quantity) if lines[0].quantity else 0,
            paid_amount=paid_amount,
            remaining_amount=remaining_amount,
            payment_channel=payment_channel,
            lines=lines,
        )

    if quantity <= 0:
        raise PurchaseServiceError("Quantité invalide.")

    product = find_product_by_name(str(intent["product"]), db)
    paid_amount = 0 if payment_channel == "credit" else total_amount
    remaining_amount = total_amount - paid_amount

    return ResolvedPurchase(
        supplier=supplier,
        product=product,
        quantity=quantity,
        total_amount=total_amount,
        unit_cost=round(total_amount / quantity),
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_channel=payment_channel,
    )


def build_purchase_create_payload(resolved: ResolvedPurchase) -> PurchaseCreate:
    return PurchaseCreate(
        supplier_id=resolved.supplier.id,
        items=[
            PurchaseItemCreate(
                product_id=line.product.id,
                quantity=line.quantity,
                unit_cost=(
                    round(line.line_total / line.quantity)
                    if line.quantity
                    else 0
                ),
            )
            for line in resolved.lines
        ],
        paid_amount=resolved.paid_amount,
        payment_channel=resolved.payment_channel,
    )


def create_purchase_from_intent(intent: dict[str, Any], db: Session, create_purchase_func: Callable[[PurchaseCreate, Session], Any]) -> Any:
    return create_purchase_func(build_purchase_create_payload(resolve_purchase_intent(intent, db)), db)


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
