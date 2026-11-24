import csv
import io
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import get_current_merchant
from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.shop import Shop
from app.models.shop_operation import ShopOperation
from app.models.supplier import Supplier
from app.rbac import require_permission
from app.services.shop_context_service import get_current_shop_id

router = APIRouter(prefix="/exports", tags=["PWA exports"])
MAX_ROWS = 50000


def _context(db):
    merchant_id = get_current_merchant(db)
    if merchant_id is None:
        raise HTTPException(401, "Authentification requise")

    shop_id = get_current_shop_id(db)
    if shop_id is None:
        raise HTTPException(409, "Sélectionne une boutique.")

    shop = db.query(Shop).filter(
        Shop.id == shop_id,
        Shop.merchant_id == merchant_id,
    ).first()
    if shop is None:
        raise HTTPException(403, "Boutique inaccessible.")

    return merchant_id, shop


def _period(query, model, since, until):
    if since and until and since > until:
        raise HTTPException(400, "La date de début dépasse la date de fin.")
    if until == date.max:
        raise HTTPException(400, "Date de fin hors limites.")

    if since:
        query = query.filter(
            model.created_at >= datetime.combine(since, time.min)
        )
    if until:
        query = query.filter(
            model.created_at < datetime.combine(
                until + timedelta(days=1), time.min
            )
        )
    return query


def _query(db, model, entity_type, merchant_id, shop_id):
    return db.query(model).join(
        ShopOperation,
        (ShopOperation.entity_type == entity_type)
        & (ShopOperation.entity_id == model.id),
    ).filter(
        model.merchant_id == merchant_id,
        ShopOperation.merchant_id == merchant_id,
        ShopOperation.shop_id == shop_id,
    )


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        # Empêcher un libellé de devenir une formule dans un tableur.
        if value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        if value.startswith(("\t", "\r", "\n")):
            return "'" + value
    return value


def _csv_response(headers, rows, filename):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_cell(value) for value in row])

    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _bounded(query):
    rows = query.limit(MAX_ROWS + 1).all()
    if len(rows) > MAX_ROWS:
        raise HTTPException(
            413,
            "Export trop volumineux. Choisis une période plus courte.",
        )
    return rows


@router.get("/{kind}.csv")
def export_csv(
    kind: Literal["sales", "purchases", "expenses"],
    since: date | None = None,
    until: date | None = None,
    mode: Literal["summary", "details"] = "summary",
    include_cancelled: bool = False,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("report.read")),
):
    merchant_id, shop = _context(db)
    shop_id = shop.id
    shop_name = shop.name

    if kind == "expenses":
        query = _query(
            db, FinancialEntry, "financial_entry", merchant_id, shop_id
        ).filter(FinancialEntry.entry_type == "expense")
        query = _period(query, FinancialEntry, since, until)
        entries = _bounded(query.order_by(
            FinancialEntry.created_at, FinancialEntry.id
        ))
        headers = [
            "depense_id", "date_utc", "boutique_id", "boutique",
            "categorie", "libelle", "montant", "devise",
            "mode_paiement", "note",
        ]
        rows = [
            [
                entry.id, entry.created_at, shop_id, shop_name,
                entry.category, entry.label, entry.amount, "XOF",
                entry.channel, entry.note,
            ]
            for entry in entries
        ]
    else:
        is_sale = kind == "sales"
        model = Sale if is_sale else Purchase
        item_model = SaleItem if is_sale else PurchaseItem
        partner_model = Customer if is_sale else Supplier
        partner_id = model.customer_id if is_sale else model.supplier_id
        entity_type = "sale" if is_sale else "purchase"

        query = _query(db, model, entity_type, merchant_id, shop_id)
        query = _period(query, model, since, until)
        if not include_cancelled:
            query = query.filter(model.status != "cancelled")

        if mode == "summary":
            query = query.outerjoin(
                partner_model,
                (partner_model.id == partner_id)
                & (partner_model.merchant_id == merchant_id),
            ).add_columns(partner_model.name)
            entries = _bounded(query.order_by(model.created_at, model.id))
            headers = [
                "operation_id", "reference", "date_utc",
                "boutique_id", "boutique", "tiers_id", "tiers",
                "total", "paye_actuel", "reste_actuel", "devise",
                "statut", "echeance", "date_annulation",
            ]
            rows = [
                [
                    entry.id,
                    entry.reference_number if is_sale else entry.id,
                    entry.created_at, shop_id, shop_name,
                    entry.customer_id if is_sale else entry.supplier_id,
                    name or ("Vente comptoir" if is_sale else ""),
                    entry.total_amount, entry.paid_amount,
                    entry.remaining_amount, "XOF", entry.status,
                    entry.due_date, getattr(entry, "cancelled_at", None),
                ]
                for entry, name in entries
            ]
        else:
            item_parent = (
                item_model.sale_id if is_sale else item_model.purchase_id
            )
            query = query.join(
                item_model, item_parent == model.id
            ).outerjoin(
                Product,
                (Product.id == item_model.product_id)
                & (Product.merchant_id == merchant_id),
            ).add_entity(item_model).add_columns(Product.name)
            entries = _bounded(query.order_by(
                model.created_at, model.id, item_model.id
            ))
            headers = [
                "operation_id", "reference", "date_utc",
                "boutique_id", "boutique", "ligne_id", "produit_id",
                "produit", "quantite",
                "prix_unitaire" if is_sale else "cout_unitaire",
                "total_ligne", "devise", "statut_operation",
            ]
            rows = [
                [
                    entry.id,
                    entry.reference_number if is_sale else entry.id,
                    entry.created_at, shop_id, shop_name,
                    item.id, item.product_id, name, item.quantity,
                    item.unit_price if is_sale else item.unit_cost,
                    item.line_total, "XOF", entry.status,
                ]
                for entry, item, name in entries
            ]

    label = {
        "sales": "ventes",
        "purchases": "achats",
        "expenses": "depenses",
    }[kind]
    filename = (
        f"whatzabi-{label}-{mode}-boutique-{shop_id}-"
        f"{since or 'debut'}-{until or 'fin'}.csv"
    )
    return _csv_response(headers, rows, filename)
