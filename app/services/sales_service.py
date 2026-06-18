from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.product import Product
from app.schemas.sale import SaleCreate, SaleItemCreate


class SaleServiceError(Exception):
    pass


@dataclass
class ResolvedSale:
    customer: Customer
    product: Product
    quantity: int
    total_amount: int
    paid_amount: int
    remaining_amount: int
    payment_channel: str

    @property
    def unit_price(self) -> int:
        if self.quantity <= 0:
            return 0
        return round(self.total_amount / self.quantity)


def normalize_channel(value: str) -> str:
    lower = value.lower()
    if "moov" in lower:
        return "moov_money"
    if "mtn" in lower:
        return "mtn_momo"
    return "cash"


def find_customer_by_name(name: str, db: Session) -> Customer:
    customer = db.query(Customer).filter(Customer.name.ilike(name)).first()
    if not customer:
        raise SaleServiceError(f"Client introuvable : {name}")
    return customer


def find_product_by_name(name: str, db: Session) -> Product:
    product = db.query(Product).filter(Product.name.ilike(name)).first()
    if not product:
        raise SaleServiceError(f"Produit introuvable : {name}")
    return product


def resolve_sale_intent(intent: dict[str, Any], db: Session) -> ResolvedSale:
    if intent.get("type") != "sale":
        raise SaleServiceError("L'intention fournie n'est pas une vente.")

    quantity = int(intent.get("quantity", 0))
    total_amount = int(intent.get("amount", 0))
    remaining_amount = int(intent.get("remaining", 0))
    payment_channel = normalize_channel(str(intent.get("payment", "cash")))

    if quantity <= 0:
        raise SaleServiceError("Quantité invalide.")
    if total_amount <= 0:
        raise SaleServiceError("Montant invalide.")
    if remaining_amount < 0:
        raise SaleServiceError("Montant restant invalide.")
    if remaining_amount > total_amount:
        raise SaleServiceError("Le reste dû ne peut pas dépasser le montant total.")

    customer = find_customer_by_name(str(intent["customer"]), db)
    product = find_product_by_name(str(intent["product"]), db)

    if product.stock < quantity:
        raise SaleServiceError(
            f"Stock insuffisant pour {product.name} : stock {product.stock}, demandé {quantity}"
        )

    paid_amount = max(0, total_amount - remaining_amount)

    return ResolvedSale(
        customer=customer,
        product=product,
        quantity=quantity,
        total_amount=total_amount,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_channel=payment_channel,
    )


def build_sale_create_payload(resolved: ResolvedSale) -> SaleCreate:
    return SaleCreate(
        customer_id=resolved.customer.id,
        items=[
            SaleItemCreate(
                product_id=resolved.product.id,
                quantity=resolved.quantity,
            )
        ],
        paid_amount=resolved.paid_amount,
        payment_channel=resolved.payment_channel,
    )


def create_sale_from_intent(
    intent: dict[str, Any],
    db: Session,
    create_sale_func: Callable[[SaleCreate, Session], Any],
) -> Any:
    resolved = resolve_sale_intent(intent, db)
    payload = build_sale_create_payload(resolved)
    return create_sale_func(payload, db)


def preview_sale_from_intent(intent: dict[str, Any], db: Session) -> dict[str, Any]:
    resolved = resolve_sale_intent(intent, db)

    return {
        "customer_id": resolved.customer.id,
        "customer_name": resolved.customer.name,
        "product_id": resolved.product.id,
        "product_name": resolved.product.name,
        "quantity": resolved.quantity,
        "unit_price": resolved.unit_price,
        "total_amount": resolved.total_amount,
        "paid_amount": resolved.paid_amount,
        "remaining_amount": resolved.remaining_amount,
        "payment_channel": resolved.payment_channel,
        "stock_before": resolved.product.stock,
        "stock_after": resolved.product.stock - resolved.quantity,
    }