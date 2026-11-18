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

    from app.services.finance_time import zone, bounds
    start,end=bounds(since,until,zone(query.session,get_current_shop_id(query.session)))
    if since:
        query = query.filter(
            model.created_at >= start.replace(tzinfo=None)
        )
    if until:
        query = query.filter(
            model.created_at < end.replace(tzinfo=None)
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
    kind: Literal["sales", "purchases", "expenses", "cash", "supplier_payments", "receivables", "payables"],
    since: date | None = None,
    until: date | None = None,
    mode: Literal["summary", "details"] = "summary",
    include_cancelled: bool = False,
    channel: str | None = None,
    movement: Literal["receipt", "refund"] | None = None,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("report.read")),
):
    merchant_id, shop = _context(db)
    shop_id = shop.id
    shop_name = shop.name

    if kind in ('receivables', 'payables'):
        from app.services.commercial_details import details
        data=details(db,kind,since,until,1,MAX_ROWS+1)
        if data['count']>MAX_ROWS: raise HTTPException(413,'Export trop volumineux ; réduire le périmètre')
        from datetime import datetime, timezone
        read_at=datetime.now(timezone.utc).isoformat()
        headers=['operation_id','boutique_id','reste_actuel','devise_operation','date_operation','base','lecture_utc','fuseau']
        rows=[[r['operation_id'],shop_id,r['amount'],r['currency_code'] or 'UNKNOWN',r['effective_at'],'CURRENT_NOT_PERIOD_END',read_at,data['business_timezone']] for r in data['rows']]
        return _csv_response(headers,rows,f'whatzabi-{kind}-actuels-boutique-{shop_id}.csv')
    if kind == 'supplier_payments':
        from app.services.commercial_details import details
        data=details(db,kind,since,until,1,MAX_ROWS+1)
        if data['count']>MAX_ROWS: raise HTTPException(413,'Export trop volumineux ; réduire la période')
        headers=['paiement_id','achat_id','boutique_id','montant','canal','date_effective','horodatage_technique','provenance','qualite_date','fuseau','debut_inclus','fin_incluse','devise_operation']
        rows=[[r['id'],r['operation_id'],shop_id,r['amount'],r['channel'],r['effective_at'],r['recorded_at'],r['provenance'],
            'known' if r['effective_at'] else 'UNKNOWN_EXCLUDED_FROM_PERIOD_TOTALS',data['business_timezone'],since,until,r['currency_code'] or 'UNKNOWN'] for r in data['rows']]
        return _csv_response(headers,rows,f'whatzabi-decaissements-fournisseurs-boutique-{shop_id}.csv')
    if kind == 'cash':
        from sqlalchemy import text
        from app.services.finance_time import zone, bounds
        tz=zone(db,shop_id);start,end=bounds(since,until,tz)
        params={'m':merchant_id,'shop':shop_id}
        filters=[]
        if start:filters.append('(effective_at >= :start OR effective_at IS NULL)');params['start']=start
        if end:filters.append('(effective_at < :end OR effective_at IS NULL)');params['end']=end
        if channel:filters.append('channel=:channel');params['channel']=channel
        if movement:filters.append('kind=:movement');params['movement']=movement
        where=' AND '.join(filters) or 'TRUE'
        entries=db.execute(text(f"""
            WITH cash AS (
              SELECT s.currency_code,'receipt' kind,p.id,s.id sale_id,p.amount,p.channel,p.effective_at,
                p.paid_at AT TIME ZONE 'UTC' recorded_at,p.id::text original_payment_ids
              FROM payments p JOIN sales s ON s.id=p.sale_id
              WHERE s.merchant_id=:m AND (p.merchant_id=:m OR p.merchant_id IS NULL)
              AND EXISTS(SELECT 1 FROM shop_operations o WHERE o.merchant_id=:m AND o.shop_id=:shop AND o.entity_type='sale' AND o.entity_id=s.id)
              UNION ALL
              SELECT (SELECT s.currency_code FROM sales s WHERE s.id=r.sale_id),'refund',r.id,r.sale_id,-r.amount,r.channel,r.effective_at,r.recorded_at,
                (SELECT string_agg(a.payment_id::text,',' ORDER BY a.payment_id) FROM refund_allocations a WHERE a.refund_id=r.id)
              FROM customer_refunds r WHERE r.merchant_id=:m AND r.shop_id=:shop
            ) SELECT * FROM cash WHERE {where} ORDER BY effective_at NULLS LAST,kind,id
        """),params).mappings().all()
        if len(entries)>MAX_ROWS:raise HTTPException(413,'Export trop volumineux')
        headers=['type','id','vente_id','boutique_id','montant_signe','canal','date_effective','horodatage_enregistrement_ou_legacy','fuseau_metier','qualite_date','paiements_origine','devise_operation']
        rows=[[r['kind'],r['id'],r['sale_id'],shop_id,r['amount'],r['channel'],
            r['effective_at'].astimezone(tz).isoformat() if r['effective_at'] else '',r['recorded_at'].isoformat(),tz.key,
            'known' if r['effective_at'] else 'UNKNOWN_EXCLUDED_FROM_PERIOD_TOTALS',r['original_payment_ids'],r['currency_code'] or 'UNKNOWN'] for r in entries]
        return _csv_response(headers,rows,f'whatzabi-encaissements-boutique-{shop_id}.csv')
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
                entry.category, entry.label, entry.amount, entry.currency_code or "UNKNOWN",
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
                    entry.remaining_amount, entry.currency_code or "UNKNOWN", entry.status,
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
                    item.line_total, entry.currency_code or "UNKNOWN", entry.status,
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
