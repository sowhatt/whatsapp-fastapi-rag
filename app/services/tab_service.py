"""
Gestion des additions ouvertes (usage restaurant/bar) : une table
accumule des articles au fil des commandes, consultable à tout
moment, soldée en une seule fois à la fin — contrairement à une vente
classique qui est un événement fermé et immédiat.

À la clôture, l'addition se transforme en une vraie vente (même
mécanisme que n'importe quelle autre vente : déduit le stock, crédite
le client si besoin), pour que le bilan et l'historique restent
cohérents entre usage restaurant et usage commerce classique.
"""
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.open_tab import OpenTab, OpenTabItem
from app.models.product import Product
from app.schemas.sale import SaleCreate, SaleItemCreate
from app.services.sales_service import find_product_candidates


class TabError(Exception):
    pass


def _format_currency(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def _get_open_tab(table_name: str, db: Session) -> OpenTab | None:
    return (
        db.query(OpenTab)
        .filter(OpenTab.table_name.ilike(table_name.strip()), OpenTab.status == "open")
        .first()
    )


def add_items_to_tab(table_name: str, items: list[dict[str, Any]], db: Session) -> str:
    table_name = table_name.strip()
    resolved_items = []
    for item in items:
        product_name = str(item.get("product") or "").strip()
        quantity = int(item.get("quantity") or 0)
        if not product_name or quantity <= 0:
            raise TabError(f"Article incomplet : « {product_name or '?'} » (quantité {quantity}).")

        candidates = find_product_candidates(product_name, db)
        if len(candidates) == 0:
            raise TabError(
                f"Le produit {product_name} n'existe pas encore au catalogue. "
                "Crée-le d'abord, puis réessaie."
            )
        if len(candidates) > 1:
            options = ", ".join(p.name for p in candidates[:5])
            raise TabError(f"Plusieurs produits correspondent à « {product_name} » : {options}. Précise le produit.")

        product = candidates[0]
        resolved_items.append((product, quantity))

    tab = _get_open_tab(table_name, db)
    if tab is None:
        tab = OpenTab(table_name=table_name, status="open", total_amount=0)
        db.add(tab)
        db.flush()

    lines_summary = []
    for product, quantity in resolved_items:
        line_total = int(product.price) * quantity
        db.add(
            OpenTabItem(
                tab_id=tab.id,
                product_id=product.id,
                product_name=product.name,
                unit=product.unit or "",
                quantity=quantity,
                unit_price=product.price,
                line_total=line_total,
            )
        )
        tab.total_amount += line_total
        lines_summary.append(f"{quantity} {product.unit or ''} {product.name}".replace("  ", " "))

    db.commit()

    detail = ", ".join(lines_summary)
    return (
        f"✅ Ajouté à l'addition de {table_name} : {detail}.\n"
        f"Total en cours : {_format_currency(tab.total_amount)}."
    )


def render_tab(table_name: str, db: Session) -> str:
    tab = _get_open_tab(table_name, db)
    if tab is None:
        return f"Aucune addition ouverte pour {table_name}."

    items = db.query(OpenTabItem).filter(OpenTabItem.tab_id == tab.id).order_by(OpenTabItem.created_at).all()
    lines = [f"🧾 Addition — {table_name}", ""]
    for item in items:
        lines.append(f"• {item.quantity} {item.unit} {item.product_name} — {_format_currency(item.line_total)}")
    lines.append("")
    lines.append(f"Total : {_format_currency(tab.total_amount)}")
    return "\n".join(lines)


def close_tab(
    table_name: str,
    payment_channel: str,
    db: Session,
    create_sale_func: Callable[[SaleCreate, Session], Any],
) -> str:
    table_name = table_name.strip()
    tab = _get_open_tab(table_name, db)
    if tab is None:
        raise TabError(f"Aucune addition ouverte pour {table_name}.")

    items = db.query(OpenTabItem).filter(OpenTabItem.tab_id == tab.id).all()
    if not items:
        raise TabError(f"L'addition de {table_name} est vide, rien à encaisser.")

    customer = db.query(Customer).filter(Customer.name.ilike(table_name)).first()
    if customer is None:
        customer = Customer(name=table_name, debt=0)
        db.add(customer)
        db.flush()

    payload = SaleCreate(
        customer_id=customer.id,
        items=[
            SaleItemCreate(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in items
        ],
        paid_amount=tab.total_amount,
        payment_channel=payment_channel,
    )
    sale = create_sale_func(payload, db)

    tab.status = "closed"
    from datetime import datetime

    tab.closed_at = datetime.utcnow()
    db.commit()

    return (
        f"✅ Addition de {table_name} soldée — {_format_currency(tab.total_amount)} ({payment_channel}).\n"
        f"Référence : vente n°{sale.reference_number}."
    )
