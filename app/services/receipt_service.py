"""
Reçu de vente WhatsApp.

Le commerçant dit « envoie le reçu à Awa » (ou « facture pour Awa »,
« reçu de la vente 5 ») et reçoit un reçu formaté qu'il peut
transférer à son client en un geste. Aucune confirmation nécessaire :
un reçu ne modifie rien, il ne fait que lire.
"""
import os
import re
import unicodedata
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem


_STOPWORDS = {
    "envoie", "envoi", "envoyer", "donne", "donner", "fais", "faire",
    "genere", "generer", "genere", "moi", "le", "la", "les", "un", "une",
    "recu", "facture", "de", "du", "des", "pour", "a", "au",
    "client", "cliente", "vente", "derniere", "dernier",
    "stp", "svp", "plait", "il", "te", "s",
}


def _normalize(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", text.lower())
    lowered = "".join(c for c in lowered if not unicodedata.combining(c))
    return " ".join(lowered.split())


def is_receipt_request(text: str) -> bool:
    normalized = _normalize(text)
    words = set(re.findall(r"[a-z]+", normalized))
    return bool(words & {"recu", "facture"}) and len(normalized.split()) <= 8


def _extract_sale_reference(text: str) -> int | None:
    match = re.search(
        r"vente\s*(?:n°|n\s*°|no|numero|numéro)?\s*(\d+)",
        _normalize(text),
    )
    return int(match.group(1)) if match else None


def _extract_customer_name(text: str) -> str | None:
    tokens = [
        token
        for token in re.findall(r"[a-zà-ÿ]+", _normalize(text))
        if token not in _STOPWORDS
    ]
    return " ".join(tokens) if tokens else None


def _format_currency(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def _find_customer(name: str, db: Session) -> tuple[Customer | None, str | None]:
    from app.services.text_normalize import find_customer_accent_insensitive

    exact = find_customer_accent_insensitive(name, db)
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


def render_receipt(
    sale: Sale,
    customer_name: str,
    lines: list[dict[str, Any]],
) -> str:
    shop_name = os.getenv("SHOP_NAME", "Ma boutique")
    created = sale.created_at or datetime.utcnow()

    parts = [
        f"🧾 REÇU — {shop_name}",
        f"Réf : vente n°{sale.id} · {created.strftime('%d/%m/%Y %H:%M')}",
        f"Client : {customer_name}",
        "━━━━━━━━━━━━━━",
    ]
    for line in lines:
        quantity = line.get("quantity") or 0
        unit = str(line.get("unit") or "").strip()
        product = str(line.get("product") or "Produit")
        label = f"{quantity} {unit} {product}".replace("  ", " ").strip()
        parts.append(f"• {label} — {_format_currency(line.get('line_total') or 0)}")
    parts.extend(
        [
            "━━━━━━━━━━━━━━",
            f"Total : {_format_currency(sale.total_amount)}",
            f"Payé : {_format_currency(sale.paid_amount)}",
        ]
    )
    if (sale.remaining_amount or 0) > 0:
        parts.append(f"Reste dû : {_format_currency(sale.remaining_amount)}")
    parts.extend(
        [
            "",
            "Merci de votre confiance 🙏",
            "Reçu généré par Whatzabi",
        ]
    )
    return "\n".join(parts)


def handle_receipt_request(text: str, db: Session) -> str:
    reference = _extract_sale_reference(text)

    if reference is not None:
        sale = (
            db.query(Sale)
            .filter(Sale.id == reference, Sale.status != "cancelled")
            .first()
        )
        if not sale:
            return f"Aucune vente n°{reference} trouvée."
    else:
        customer = None
        name = _extract_customer_name(text)
        if name:
            customer, error = _find_customer(name, db)
            if error:
                return error
        query = db.query(Sale).filter(Sale.status != "cancelled")
        if customer:
            query = query.filter(Sale.customer_id == customer.id)
        sale = query.order_by(Sale.created_at.desc(), Sale.id.desc()).first()
        if not sale:
            cible = f" pour {customer.name}" if customer else ""
            return f"Aucune vente enregistrée{cible}."

    customer_name = "Client"
    if sale.customer_id:
        row = db.query(Customer).filter(Customer.id == sale.customer_id).first()
        if row:
            customer_name = row.name

    lines: list[dict[str, Any]] = []
    items = (
        db.query(SaleItem, Product)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(SaleItem.sale_id == sale.id)
        .all()
    )
    for item, product in items:
        lines.append(
            {
                "quantity": item.quantity,
                "unit": product.unit,
                "product": product.name,
                "line_total": item.line_total,
            }
        )

    return render_receipt(sale, customer_name, lines)
