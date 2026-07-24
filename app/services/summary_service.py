"""
Bilans (jour / semaine / mois) : chiffre d'affaires, marge réelle,
dépenses par catégorie, et détail des créances/dettes.

La marge utilise le prix d'achat catalogue (Product.purchase_price)
face au prix réellement encaissé sur chaque ligne de vente
(SaleItem.line_total), pas le prix catalogue théorique — cohérent
avec le fait que les prix se négocient sur le marché.
"""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.supplier import Supplier


PERIOD_LABELS = {
    "day": "du jour",
    "week": "de la semaine",
    "month": "du mois",
}

EXPENSE_CATEGORY_LABELS = {
    "marchandises": "Marchandises",
    "transport": "Transport",
    "livraison": "Livraison",
    "loyer": "Loyer",
    "electricite": "Électricité",
    "eau": "Eau",
    "salaire": "Salaire",
    "autre": "Autre",
}


def _period_start(period: str, now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    if period == "week":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day - timedelta(days=start_of_day.weekday())
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_period_summary_data(db: Session, period: str = "day") -> dict:
    since = _period_start(period)

    sales_total = (
        db.query(func.coalesce(func.sum(Sale.total_amount), 0))
        .filter(Sale.status != "cancelled", Sale.created_at >= since)
        .scalar()
    )
    sales_count = (
        db.query(func.count(Sale.id))
        .filter(Sale.status != "cancelled", Sale.created_at >= since)
        .scalar()
    )
    purchases_total = (
        db.query(func.coalesce(func.sum(Purchase.total_amount), 0))
        .filter(Purchase.status != "cancelled", Purchase.created_at >= since)
        .scalar()
    )

    # Marge réelle : somme des lignes vendues moins leur coût d'achat
    # catalogue, sur la période. Les ventes annulées sont exclues.
    margin_rows = (
        db.query(SaleItem.line_total, SaleItem.quantity, Product.purchase_price)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(Sale.status != "cancelled", Sale.created_at >= since)
        .all()
    )
    margin = sum(
        int(line_total or 0) - int(purchase_price or 0) * int(quantity or 0)
        for line_total, quantity, purchase_price in margin_rows
    )

    encashed_by_channel: dict[str, int] = {}
    for channel, total in (
        db.query(FinancialEntry.channel, func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(
            FinancialEntry.entry_type == "income",
            FinancialEntry.created_at >= since,
        )
        .group_by(FinancialEntry.channel)
        .all()
    ):
        encashed_by_channel[channel] = int(total)

    expenses_by_category: dict[str, int] = {}
    # Important : on construit l'expression une seule fois et on la
    # réutilise en SELECT et en GROUP BY. PostgreSQL exige que les deux
    # clauses portent exactement la même expression ; deux appels
    # séparés à func.coalesce(...) génèrent deux paramètres liés
    # distincts (même si la valeur "autre" est identique), et Postgres
    # refuse alors la requête avec un GroupingError.
    category_expr = func.coalesce(FinancialEntry.category, "autre")
    for category, total in (
        db.query(
            category_expr,
            func.coalesce(func.sum(FinancialEntry.amount), 0),
        )
        .filter(
            FinancialEntry.entry_type == "expense",
            FinancialEntry.created_at >= since,
        )
        .group_by(category_expr)
        .all()
    ):
        expenses_by_category[category] = int(total)
    expenses_total = sum(expenses_by_category.values())

    top_debtors = (
        db.query(Customer.name, Customer.debt)
        .filter(Customer.debt > 0)
        .order_by(Customer.debt.desc())
        .limit(5)
        .all()
    )
    customer_debt_total = (
        db.query(func.coalesce(func.sum(Customer.debt), 0)).scalar()
    )
    supplier_debt_total = (
        db.query(func.coalesce(func.sum(Supplier.debt), 0)).scalar()
    )

    return {
        "period": period,
        "since": since,
        "sales_total": int(sales_total or 0),
        "sales_count": int(sales_count or 0),
        "purchases_total": int(purchases_total or 0),
        "margin": margin,
        "encashed_by_channel": encashed_by_channel,
        "expenses_by_category": expenses_by_category,
        "expenses_total": expenses_total,
        "top_debtors": [(name, int(debt)) for name, debt in top_debtors],
        "customer_debt_total": int(customer_debt_total or 0),
        "supplier_debt_total": int(supplier_debt_total or 0),
    }


def get_daily_summary_data(db: Session):
    """Conservé pour compatibilité ascendante (ancien format global)."""
    activity = {
        "sales_total": db.query(func.coalesce(func.sum(Sale.total_amount), 0))
        .filter(Sale.status != "cancelled")
        .scalar(),
        "purchases_total": db.query(func.coalesce(func.sum(Purchase.total_amount), 0))
        .filter(Purchase.status != "cancelled")
        .scalar(),
        "customer_debt": db.query(func.coalesce(func.sum(Customer.debt), 0)).scalar(),
        "supplier_debt": db.query(func.coalesce(func.sum(Supplier.debt), 0)).scalar(),
    }

    manual_cashflow = {
        "manual_income": db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(FinancialEntry.entry_type == "income", FinancialEntry.origin_kind == "manual")
        .scalar(),
        "manual_expense": db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(FinancialEntry.entry_type == "expense", FinancialEntry.origin_kind == "manual")
        .scalar(),
    }

    manual_cashflow["manual_net"] = manual_cashflow["manual_income"] - manual_cashflow["manual_expense"]

    return {
        "activity": activity,
        "manual_cashflow": manual_cashflow,
    }


def _format_currency(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def render_period_summary(data: dict) -> str:
    label = PERIOD_LABELS.get(data["period"], "du jour")
    lines = [f"📊 Bilan {label}", ""]
    lines.append(
        f"Ventes : {data['sales_count']} opération(s) — {_format_currency(data['sales_total'])}"
    )
    if data["encashed_by_channel"]:
        parts = ", ".join(
            f"{k} {_format_currency(v)}" for k, v in data["encashed_by_channel"].items()
        )
        lines.append(f"Encaissé : {parts}")
    if data["purchases_total"]:
        lines.append(f"Achats : {_format_currency(data['purchases_total'])}")

    if data["expenses_total"]:
        detail = ", ".join(
            f"{EXPENSE_CATEGORY_LABELS.get(cat, cat.capitalize())} {_format_currency(v)}"
            for cat, v in sorted(data["expenses_by_category"].items(), key=lambda x: -x[1])
        )
        lines.append(f"Dépenses : {_format_currency(data['expenses_total'])} ({detail})")

    lines.append("")
    lines.append(f"💰 Marge estimée : {_format_currency(data['margin'])}")

    if data["top_debtors"]:
        detail = ", ".join(f"{name} {_format_currency(debt)}" for name, debt in data["top_debtors"])
        lines.append("")
        lines.append(f"On te doit au total {_format_currency(data['customer_debt_total'])} : {detail}")
    if data["supplier_debt_total"]:
        lines.append(f"Tu dois aux fournisseurs : {_format_currency(data['supplier_debt_total'])}")

    return "\n".join(lines)
