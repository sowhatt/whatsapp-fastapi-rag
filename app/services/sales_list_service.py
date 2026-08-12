"""
Listes de ventes WhatsApp.

Trois vues, toutes déclenchées en lecture seule (aucune confirmation,
n'abandonne jamais un workflow en cours) :
  - liste chronologique : « liste des ventes », « historique des ventes »
  - par client : « ventes par client »
  - par catégorie de produit : « ventes par catégorie »

Une variante « ventes de Awa » filtre la liste chronologique sur un
client précis.
"""
import re
import unicodedata
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.table_utils import render_table, smart_truncate
from app.models.category import Category
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.summary_service import resolve_period_from_text


_STOPWORDS = {
    "liste", "listes", "historique", "des", "de", "du", "les", "la", "le",
    "vente", "ventes", "client", "clients", "par", "toutes", "tout",
    "moi", "mes", "montre", "affiche", "voir", "stp", "svp",
}


def _normalize(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", text.lower())
    lowered = "".join(c for c in lowered if not unicodedata.combining(c))
    return " ".join(lowered.split())


def is_sales_list_request(text: str) -> bool:
    normalized = _normalize(text)
    if re.search(r"\b(liste|historique)\b.*\bventes?\b", normalized):
        return True
    if re.search(r"\bventes?\s+par\s+(client|categorie|cat[eé]gorie)\b", text.lower()):
        return True
    if re.search(r"\bventes?\s+(de|du|pour)\s+\w", normalized) and "categorie" not in normalized and "prix" not in normalized:
        return True
    return False


def _format_currency(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def _extract_customer_name(text: str) -> str | None:
    match = re.search(r"ventes?\s+(?:de|du|pour)\s+(.+)", text, re.IGNORECASE)
    if not match:
        return None
    tokens = [
        token
        for token in re.findall(r"[a-zà-ÿ]+", _normalize(match.group(1)))
        if token not in _STOPWORDS
    ]
    return " ".join(tokens) if tokens else None


def _find_customer(name: str, db: Session) -> tuple[Customer | None, str | None]:
    exact = db.query(Customer).filter(Customer.name.ilike(name)).first()
    if exact:
        return exact, None
    escaped = name.replace("%", "\\%").replace("_", "\\_")
    partial = (
        db.query(Customer)
        .filter(Customer.name.ilike(f"%{escaped}%"))
        .order_by(Customer.name)
        .all()
    )
    if len(partial) == 1:
        return partial[0], None
    if len(partial) > 1:
        options = ", ".join(c.name for c in partial[:5])
        return None, f"Plusieurs clients correspondent à « {name} » : {options}. Précise le nom."
    return None, f"Client introuvable : {name}."


def _sale_items_summary(sale_id: int, db: Session) -> str:
    items = (
        db.query(SaleItem, Product)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(SaleItem.sale_id == sale_id)
        .all()
    )
    if not items:
        return "—"
    if len(items) == 1:
        item, product = items[0]
        unit = str(product.unit or "").strip()
        return f"{item.quantity} {unit} {product.name}".replace("  ", " ").strip()
    first_item, first_product = items[0]
    return f"{first_product.name} + {len(items) - 1} autre(s)"


def render_sale_detail(sale_id: int, db: Session) -> str:
    """
    Fiche détaillée d'UNE vente précise, consultable à tout moment
    par son numéro de référence (contrairement à la liste générale,
    qui ne montre qu'un résumé des ventes récentes). Utile pour
    revoir le détail avant de décider de l'annuler, par exemple.
    """
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        return f"Vente n°{sale_id} introuvable."

    customer_name = None
    if sale.customer_id:
        customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()
        customer_name = customer.name if customer else None

    items = (
        db.query(SaleItem, Product)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(SaleItem.sale_id == sale.id)
        .all()
    )

    date_label = sale.created_at.strftime("%d/%m/%Y %H:%M") if sale.created_at else "?"
    status_label = {
        "paid": "Payée",
        "credit": "À crédit",
        "cancelled": "Annulée",
    }.get(sale.status, sale.status)

    lines = [f"🧾 Vente n°{sale.id}", ""]
    lines.append(f"Date : {date_label}")
    lines.append(f"Client : {customer_name or 'Non renseigné'}")
    lines.append(f"Statut : {status_label}")
    lines.append("")

    for item, product in items:
        lines.append(
            f"• {item.quantity} {product.unit or ''} {product.name} "
            f"— {_format_currency(item.unit_price)}/unité — {_format_currency(item.line_total)}".replace("  ", " ")
        )

    lines.append("")
    lines.append(f"Montant total : {_format_currency(sale.total_amount)}")
    lines.append(f"Payé : {_format_currency(sale.paid_amount)}")
    if sale.remaining_amount > 0:
        lines.append(f"Reste dû : {_format_currency(sale.remaining_amount)}")

    return "\n".join(lines)


def render_sales_list(text: str, db: Session, limit: int = 15) -> str:
    lower = text.lower()

    if re.search(r"\bventes?\s+par\s+(client|clients)\b", lower):
        return _render_by_client(text, db)
    if re.search(r"\bventes?\s+par\s+cat[eé]gorie", lower):
        return _render_by_category(text, db)
    return _render_chronological(text, db, limit=limit)


def _render_chronological(text: str, db: Session, limit: int) -> str:
    customer = None
    name = _extract_customer_name(text)
    if name:
        customer, error = _find_customer(name, db)
        if error:
            return error

    query = db.query(Sale, Customer.name).outerjoin(Customer, Customer.id == Sale.customer_id)
    query = query.filter(Sale.status != "cancelled")
    if customer:
        query = query.filter(Sale.customer_id == customer.id)
    rows = query.order_by(Sale.created_at.desc()).limit(limit).all()

    if not rows:
        cible = f" pour {customer.name}" if customer else ""
        return f"Aucune vente enregistrée{cible}."

    title = f"🧾 Ventes de {customer.name}" if customer else "🧾 Dernières ventes"
    table_rows = []
    for sale, customer_name in rows:
        date_label = (sale.created_at or "").strftime("%d/%m %H:%M") if sale.created_at else "?"
        items_summary = _sale_items_summary(sale.id, db)
        # Feu tricolore : 🟢 vente entièrement payée, 🔴 solde encore
        # dû. Signal directement utile (qui me doit encore de l'argent
        # sur CETTE vente précise), pas juste décoratif.
        icone = "🔴" if (sale.remaining_amount or 0) > 0 else "🟢"
        table_rows.append(
            [
                f"#{sale.id}",
                date_label,
                (customer_name or "Client")[:12],
                items_summary[:18],
                _format_currency(sale.total_amount),
                icone,
            ]
        )

    table = render_table(
        headers=["Réf", "Date", "Client", "Produits", "Montant", ""],
        rows=table_rows,
        right_align={4},
    )
    lines = [title, "", table]
    if len(rows) == limit:
        lines.append("")
        lines.append(f"(les {limit} plus récentes)")
    return "\n".join(lines)


def _render_by_client(text: str, db: Session) -> str:
    since, until, label = resolve_period_from_text(text) if any(
        keyword in text.lower() for keyword in ("jour", "semaine", "mois", "hier")
    ) else (None, None, None)

    total_expr = func.coalesce(func.sum(Sale.total_amount), 0)
    query = (
        db.query(Customer.name, func.count(Sale.id), total_expr, Customer.debt)
        .join(Sale, Sale.customer_id == Customer.id)
        .filter(Sale.status != "cancelled")
    )
    if since is not None:
        query = query.filter(Sale.created_at >= since)
        if until is not None:
            query = query.filter(Sale.created_at < until)
    rows = query.group_by(Customer.name, Customer.debt).order_by(total_expr.desc()).all()

    if not rows:
        return "Aucune vente enregistrée pour l'instant."

    title = f"🧾 Ventes par client ({label})" if label else "🧾 Ventes par client"
    table_rows = []
    for name, count, total, debt in rows:
        # Feu tricolore sur la dette du client, pas sur son volume
        # d'achat : un client qui achète beaucoup n'est pas "en
        # danger", un client qui doit de l'argent, si.
        icone = "🔴" if (debt or 0) > 0 else "🟢"
        table_rows.append([smart_truncate(name, 16), str(count), _format_currency(total), icone])

    table = render_table(
        headers=["Client", "Ventes", "Total", ""],
        rows=table_rows,
        right_align={1, 2},
    )
    return "\n".join([title, "", table])


def _render_by_category(text: str, db: Session) -> str:
    since, until, label = resolve_period_from_text(text) if any(
        keyword in text.lower() for keyword in ("jour", "semaine", "mois", "hier")
    ) else (None, None, None)

    category_expr = func.coalesce(Category.name, "Sans catégorie")
    total_expr = func.coalesce(func.sum(SaleItem.line_total), 0)
    query = (
        db.query(category_expr, func.count(SaleItem.id), total_expr)
        .select_from(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .outerjoin(Category, Category.id == Product.category_id)
        .filter(Sale.status != "cancelled")
    )
    if since is not None:
        query = query.filter(Sale.created_at >= since)
        if until is not None:
            query = query.filter(Sale.created_at < until)
    rows = query.group_by(category_expr).order_by(total_expr.desc()).all()

    if not rows:
        return "Aucune vente enregistrée pour l'instant."

    title = f"🧾 Ventes par catégorie ({label})" if label else "🧾 Ventes par catégorie"
    table_rows = [[smart_truncate(name, 18), str(count), _format_currency(total)] for name, count, total in rows]
    table = render_table(
        headers=["Catégorie", "Lignes", "Total"],
        rows=table_rows,
        right_align={1, 2},
    )
    lines = [title, "", table]
    if all(name == "Sans catégorie" for name, *_ in rows):
        lines.append("")
        lines.append(
            "ℹ️ Aucun produit n'a encore de catégorie assignée. "
            "Ajoute une catégorie à tes produits pour affiner cette vue."
        )
    return "\n".join(lines)
