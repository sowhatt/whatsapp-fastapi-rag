from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.product import Product
from app.schemas.sale import SaleCreate, SaleItemCreate


class SaleServiceError(Exception):
    pass


@dataclass
class ResolvedSaleLine:
    product: Product
    quantity: int
    line_total: int


@dataclass
class ResolvedSale:
    customer: Customer
    product: Product
    quantity: int
    total_amount: int
    paid_amount: int
    remaining_amount: int
    payment_channel: str
    due_date: date | None = None
    lines: list[ResolvedSaleLine] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.lines:
            self.lines = [
                ResolvedSaleLine(
                    product=self.product,
                    quantity=self.quantity,
                    line_total=self.total_amount,
                )
            ]

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
    from app.services.text_normalize import find_customer_accent_insensitive

    customer = find_customer_accent_insensitive(name, db)
    if not customer:
        raise SaleServiceError(f"Client introuvable : {name}")
    return customer


def _product_tokens(value: str) -> set[str]:
    import re as _re

    return set(_re.findall(r"[a-zà-ÿ]+", str(value).lower()))


def find_product_candidates(name: str, db: Session) -> list[Product]:
    """
    Résolution en trois niveaux :
    1. correspondance exacte (« Riz parfumé » -> Riz parfumé) ;
    2. le nom dit est contenu dans un nom du catalogue
       (« riz » -> Riz parfumé, Riz ordinaire) ;
    3. un nom du catalogue est contenu dans le nom dit
       (« riz parfumé de Thaïlande » -> Riz parfumé).
    """
    cleaned = " ".join(str(name).split()).strip()
    if not cleaned:
        return []

    exact = db.query(Product).filter(Product.name.ilike(cleaned)).first()
    if exact:
        return [exact]

    escaped = cleaned.replace("%", "\\%").replace("_", "\\_")
    partial = (
        db.query(Product)
        .filter(Product.name.ilike(f"%{escaped}%"))
        .order_by(Product.name)
        .all()
    )
    if partial:
        return partial

    spoken_tokens = _product_tokens(cleaned)
    return [
        product
        for product in db.query(Product).order_by(Product.name).all()
        if _product_tokens(product.name) and _product_tokens(product.name) <= spoken_tokens
    ]


def find_product_by_name(name: str, db: Session) -> Product:
    candidates = find_product_candidates(name, db)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        options = ", ".join(product.name for product in candidates[:5])
        raise SaleServiceError(
            f"Plusieurs produits correspondent à « {name} » : {options}. "
            "Précise le produit."
        )
    raise SaleServiceError(f"Produit introuvable : {name}")


def _allocate_total(weights: list[int], total: int) -> list[int]:
    """
    Ventile un montant global sur plusieurs lignes au prorata des poids
    (valeur catalogue de chaque ligne). Si aucun poids n'est exploitable,
    la répartition est égale. Le reliquat d'arrondi va sur la dernière
    ligne pour que la somme retombe exactement sur le total.
    """
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0:
        weights = [1] * len(weights)
        weight_sum = len(weights)
    allocated = [total * weight // weight_sum for weight in weights]
    allocated[-1] += total - sum(allocated)
    return allocated


def resolve_sale_intent(intent: dict[str, Any], db: Session) -> ResolvedSale:
    if intent.get("type") != "sale":
        raise SaleServiceError("L'intention fournie n'est pas une vente.")

    quantity = int(intent.get("quantity", 0))
    total_amount = int(intent.get("amount", 0))
    remaining_amount = int(intent.get("remaining", 0))
    payment_channel = normalize_channel(str(intent.get("payment", "cash")))

    due_date_raw = intent.get("due_date")
    due_date: date | None = None
    if isinstance(due_date_raw, date):
        due_date = due_date_raw
    elif isinstance(due_date_raw, str) and due_date_raw:
        try:
            due_date = date.fromisoformat(due_date_raw)
        except ValueError:
            due_date = None

    if quantity <= 0:
        raise SaleServiceError("Quantité invalide.")
    if total_amount <= 0:
        raise SaleServiceError("Montant invalide.")
    if remaining_amount < 0:
        raise SaleServiceError("Montant restant invalide.")
    if remaining_amount > total_amount:
        raise SaleServiceError("Le reste dû ne peut pas dépasser le montant total.")

    customer = find_customer_by_name(str(intent["customer"]), db)

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
                raise SaleServiceError(
                    f"Quantité invalide pour {entry['product']}."
                )
            entry_product = find_product_by_name(str(entry["product"]), db)
            if entry_product.stock < entry_quantity:
                raise SaleServiceError(
                    f"Stock insuffisant pour {entry_product.name} : "
                    f"stock {entry_product.stock}, demandé {entry_quantity}"
                )
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
                raise SaleServiceError(
                    f"Les montants par produit ({items_sum} FCFA) ne "
                    f"correspondent pas au total annoncé ({total_amount} FCFA)."
                )
            total_amount = items_sum
        else:
            weights = [
                line_product.price * line_quantity
                for (line_product, line_quantity, _) in resolved_products
            ]
            line_totals = _allocate_total(weights, total_amount)

        lines = [
            ResolvedSaleLine(
                product=line_product,
                quantity=line_quantity,
                line_total=line_total,
            )
            for (line_product, line_quantity, _), line_total in zip(
                resolved_products, line_totals
            )
        ]
        paid_amount = max(0, total_amount - remaining_amount)
        return ResolvedSale(
            customer=customer,
            product=lines[0].product,
            quantity=lines[0].quantity,
            total_amount=total_amount,
            paid_amount=paid_amount,
            remaining_amount=remaining_amount,
            payment_channel=payment_channel,
            due_date=due_date,
            lines=lines,
        )

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
        due_date=due_date,
    )


def build_sale_create_payload(resolved: ResolvedSale) -> SaleCreate:
    return SaleCreate(
        customer_id=resolved.customer.id,
        items=[
            SaleItemCreate(
                product_id=line.product.id,
                quantity=line.quantity,
                unit_price=(
                    round(line.line_total / line.quantity)
                    if line.quantity
                    else 0
                ),
                line_total=line.line_total,
            )
            for line in resolved.lines
        ],
        paid_amount=resolved.paid_amount,
        payment_channel=resolved.payment_channel,
        due_date=resolved.due_date,
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