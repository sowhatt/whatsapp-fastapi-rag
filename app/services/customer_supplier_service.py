"""
Gestion des clients et fournisseurs, en remplacement des placeholders
"Gestion des clients/fournisseurs bientôt disponible" du menu
principal (options 3 et 4).

Deux vues symétriques pour chacun :
  - liste ("liste des clients", "mes clients") : tous les clients,
    triés par dette décroissante (les débiteurs en premier, les plus
    utiles à surveiller)
  - fiche détaillée ("client Awa", "fiche du client Awa") : historique
    complet des ventes/paiements et dette actuelle
"""
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.payment import Payment
from app.models.sale import Sale
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.models.purchase import Purchase
from app.services.table_utils import render_table, smart_truncate


def _format_currency(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def render_customer_list(db: Session) -> str:
    customers = db.query(Customer).order_by(Customer.debt.desc(), Customer.name.asc()).all()
    if not customers:
        return "Aucun client enregistré pour l'instant."

    rows = [[smart_truncate(c.name, 20), _format_currency(c.debt)] for c in customers]
    table = render_table(["Client", "Dette"], rows, right_align={1})
    total_debt = sum(c.debt for c in customers)
    return f"👥 Clients ({len(customers)})\n\n{table}\n\nDette totale : {_format_currency(total_debt)}"


def render_supplier_list(db: Session) -> str:
    suppliers = db.query(Supplier).order_by(Supplier.debt.desc(), Supplier.name.asc()).all()
    if not suppliers:
        return "Aucun fournisseur enregistré pour l'instant."

    rows = [[smart_truncate(s.name, 20), _format_currency(s.debt)] for s in suppliers]
    table = render_table(["Fournisseur", "Dette"], rows, right_align={1})
    total_debt = sum(s.debt for s in suppliers)
    return f"🚚 Fournisseurs ({len(suppliers)})\n\n{table}\n\nDette totale : {_format_currency(total_debt)}"


def _find_customer_candidates(name: str, db: Session) -> list[Customer]:
    cleaned = " ".join(str(name).split()).strip()
    if not cleaned:
        return []
    exact = db.query(Customer).filter(Customer.name.ilike(cleaned)).first()
    if exact:
        return [exact]
    return db.query(Customer).filter(Customer.name.ilike(f"%{cleaned}%")).limit(5).all()


def _find_supplier_candidates(name: str, db: Session) -> list[Supplier]:
    cleaned = " ".join(str(name).split()).strip()
    if not cleaned:
        return []
    exact = db.query(Supplier).filter(Supplier.name.ilike(cleaned)).first()
    if exact:
        return [exact]
    return db.query(Supplier).filter(Supplier.name.ilike(f"%{cleaned}%")).limit(5).all()


def render_customer_detail(name: str, db: Session) -> str:
    candidates = _find_customer_candidates(name, db)
    if len(candidates) == 0:
        return f"Client introuvable : {name}"
    if len(candidates) > 1:
        options = ", ".join(c.name for c in candidates)
        return f"Plusieurs clients correspondent à « {name} » : {options}. Précise le nom."

    customer = candidates[0]
    sales = db.query(Sale).filter(Sale.customer_id == customer.id).order_by(Sale.created_at.desc()).limit(10).all()
    payments_count = db.query(Payment).filter(Payment.customer_id == customer.id).count()

    lines = [f"👤 {customer.name}", ""]
    if customer.phone:
        lines.append(f"Téléphone : {customer.phone}")
    lines.append(f"Dette actuelle : {_format_currency(customer.debt)}")
    lines.append(f"Ventes enregistrées : {len(sales)}" + (" (10 dernières)" if len(sales) == 10 else ""))
    lines.append(f"Paiements reçus : {payments_count}")
    lines.append("")

    if sales:
        lines.append("Dernières ventes :")
        for sale in sales:
            status_icon = "🔴" if sale.remaining_amount > 0 else "🟢"
            date_label = sale.created_at.strftime("%d/%m") if sale.created_at else "?"
            lines.append(
                f"{status_icon} #{sale.id} {date_label} — {_format_currency(sale.total_amount)}"
            )

    return "\n".join(lines)


def render_supplier_detail(name: str, db: Session) -> str:
    candidates = _find_supplier_candidates(name, db)
    if len(candidates) == 0:
        return f"Fournisseur introuvable : {name}"
    if len(candidates) > 1:
        options = ", ".join(s.name for s in candidates)
        return f"Plusieurs fournisseurs correspondent à « {name} » : {options}. Précise le nom."

    supplier = candidates[0]
    purchases = (
        db.query(Purchase)
        .filter(Purchase.supplier_id == supplier.id)
        .order_by(Purchase.created_at.desc())
        .limit(10)
        .all()
    )
    payments_count = db.query(SupplierPayment).filter(SupplierPayment.supplier_id == supplier.id).count()

    lines = [f"🚚 {supplier.name}", ""]
    if supplier.phone:
        lines.append(f"Téléphone : {supplier.phone}")
    lines.append(f"Dette actuelle : {_format_currency(supplier.debt)}")
    lines.append(f"Achats enregistrés : {len(purchases)}" + (" (10 derniers)" if len(purchases) == 10 else ""))
    lines.append(f"Paiements effectués : {payments_count}")
    lines.append("")

    if purchases:
        lines.append("Derniers achats :")
        for purchase in purchases:
            status_icon = "🔴" if purchase.remaining_amount > 0 else "🟢"
            date_label = purchase.created_at.strftime("%d/%m") if purchase.created_at else "?"
            lines.append(
                f"{status_icon} #{purchase.id} {date_label} — {_format_currency(purchase.total_amount)}"
            )

    return "\n".join(lines)


_CUSTOMER_LIST_PATTERN = re.compile(r"\b(?:liste|mes)\s+(?:des\s+|de\s+)?clients?\b", re.IGNORECASE)
_SUPPLIER_LIST_PATTERN = re.compile(r"\b(?:liste|mes)\s+(?:des\s+|de\s+)?fournisseurs?\b", re.IGNORECASE)
_CUSTOMER_DETAIL_PATTERN = re.compile(
    r"\b(?:fiche\s+(?:du\s+|de\s+la\s+)?client\s+|client\s+|dette\s+(?:de\s+|du\s+client\s+)?)([a-zà-ÿ][a-zà-ÿ\s-]*?)(?:[.!?]|$)",
    re.IGNORECASE,
)
_SUPPLIER_DETAIL_PATTERN = re.compile(
    r"\b(?:fiche\s+(?:du\s+)?fournisseur\s+|fournisseur\s+)([a-zà-ÿ][a-zà-ÿ\s-]*?)(?:[.!?]|$)",
    re.IGNORECASE,
)


def is_customer_list_request(text: str) -> bool:
    return bool(_CUSTOMER_LIST_PATTERN.search(text))


def is_supplier_list_request(text: str) -> bool:
    return bool(_SUPPLIER_LIST_PATTERN.search(text))


def extract_customer_detail_name(text: str) -> str | None:
    match = _CUSTOMER_DETAIL_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def extract_supplier_detail_name(text: str) -> str | None:
    match = _SUPPLIER_DETAIL_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None
