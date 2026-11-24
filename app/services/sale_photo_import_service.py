import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, time, timezone
from app.services.sale_photo_draft_service import PhotoConflict, scoped_draft
from fastapi import HTTPException
from sqlalchemy import func
from app.db.tenant import get_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.sale_photo_import import SalePhotoImport
from app.models.shop import Shop
from app.models.shop_operation import ShopOperation
from app.models.shop_inventory import ShopInventory
from app.models.stock_movement import StockMovement
from app.models.transaction_event import TransactionEvent
from app.rbac import has_permission
from app.routers.sales import allocate_sale_number
from app.services.shop_context_service import (
    adjust_stock, get_current_shop_id,
    get_current_user_id, get_effective_stock,
)


def confirm_photo_sales(payload, db, session_hash):
    merchant_id = get_current_merchant(db)
    shop_id = get_current_shop_id(db)
    if merchant_id is None:
        raise HTTPException(401, "Authentification requise.")
    if shop_id is None or payload.shop_id != shop_id:
        raise HTTPException(409, "La boutique a changé : reprends la validation.")
    if not has_permission(db.info.get("pwa_role"), "sale.create"):
        raise HTTPException(403, "Permission requise : sale.create")
    if (
        not payload.affect_stock
        and not has_permission(db.info.get("pwa_role"), "stock.adjust")
    ):
        raise HTTPException(
            403,
            "Un manager ou propriétaire doit valider un import sans décompte du stock.",
        )
    shop = db.query(Shop).filter(
        Shop.id == shop_id,
        Shop.merchant_id == merchant_id,
    ).first()
    if shop is None:
        raise HTTPException(403, "Boutique inaccessible.")
    if payload.currency != shop.currency_code:
        raise HTTPException(
            400,
            "La devise doit correspondre à celle de la boutique. Aucune conversion automatique.",
        )
    if any(row.sale_date > datetime.now(timezone.utc).date() for row in payload.rows):
        raise HTTPException(400, "La date de vente ne peut pas être future.")

    canonical = payload.model_dump(mode="json", exclude={"confirmed"})
    canonical["rows"].sort(key=lambda row: row["row_number"])
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    try:
        # Business duplicate checks must see a transaction that committed while
        # this request waited for the merchant lock.
        if db.get_bind().dialect.name == "postgresql" and db.connection().get_isolation_level() != "READ COMMITTED":
            raise HTTPException(503, "Import requires PostgreSQL READ COMMITTED.")
        db.query(Merchant).filter(
            Merchant.id == merchant_id
        ).with_for_update().one()

        draft = scoped_draft(db, payload.draft_id, session_hash)
        if draft.response is not None:
            if draft.confirmation_hash != fingerprint:
                raise PhotoConflict("confirmed_payload_changed", "Ce brouillon est déjà confirmé. Rejoue la validation d’origine.")
            response = dict(draft.response, already_imported=True)
            db.commit()  # Release the merchant and draft locks on replay too.
            return response
        if draft.source_sha256 != payload.source_sha256:
            raise PhotoConflict("source_changed", "La photo ne correspond pas au brouillon.")
        previous = db.query(SalePhotoImport).filter(
            SalePhotoImport.merchant_id == merchant_id,
            SalePhotoImport.shop_id == shop_id,
            SalePhotoImport.source_sha256 == payload.source_sha256,
        ).first()
        if previous:
            raise PhotoConflict("source_already_imported", "Cette photo est déjà importée. Reprends le brouillon d’origine.")

        reconciliation = reconcile_totals(payload, draft.extracted)
        historical = any(row.sale_date < datetime.now(timezone.utc).date() for row in payload.rows)
        if historical and payload.affect_stock:
            if not has_permission(db.info.get("pwa_role"), "stock.adjust"):
                raise HTTPException(403, "Validation du stock historique réservée au responsable.")
            if not meaningful(payload.stock_justification):
                raise PhotoConflict("historical_stock_rule", "Justifie explicitement le décompte historique du stock actuel.")

        groups = defaultdict(list)
        needed = defaultdict(int)
        products, customers, row_numbers = {}, {}, set()

        for row in payload.rows:
            if row.row_number in row_numbers:
                raise HTTPException(400, "Numéro de ligne en double.")
            row_numbers.add(row.row_number)

            if (
                row.line_total != row.quantity * row.unit_price
                or row.paid_amount > row.line_total
            ):
                raise HTTPException(
                    400, f"Montants incohérents à la ligne {row.row_number}."
                )
            if row.paid_amount > 0 and row.payment_channel is None:
                raise HTTPException(
                    400, f"Mode de paiement requis à la ligne {row.row_number}."
                )

            if row.product_id not in products:
                product = db.query(Product).filter(
                    Product.id == row.product_id,
                    Product.merchant_id == merchant_id,
                ).populate_existing().with_for_update().first()
                if product is None:
                    raise HTTPException(404, "Produit inaccessible.")
                products[row.product_id] = product

            if row.customer_id is not None and row.customer_id not in customers:
                customer = db.query(Customer).filter(
                    Customer.id == row.customer_id,
                    Customer.merchant_id == merchant_id,
                ).first()
                if customer is None:
                    raise HTTPException(404, "Client inaccessible.")
                customers[row.customer_id] = customer

            needed[row.product_id] += row.quantity
            groups[row.sale_group].append(row)

        for rows in groups.values():
            if len({row.sale_date for row in rows}) != 1:
                raise PhotoConflict("mixed_sale_dates", "Une vente ne peut pas regrouper plusieurs journées.")
            if len({row.customer_id for row in rows}) != 1:
                raise HTTPException(
                    400, "Les lignes d’une même vente doivent avoir le même client."
                )
            channels = {
                row.payment_channel for row in rows if row.paid_amount > 0
            }
            if len(channels) > 1:
                raise HTTPException(
                    400, "Une vente doit avoir un seul mode de paiement pour cet import."
                )
            total = sum(row.line_total for row in rows)
            paid = sum(row.paid_amount for row in rows)
            if paid < total and rows[0].customer_id is None:
                raise HTTPException(
                    400, "Choisis un client pour chaque vente non intégralement payée."
                )

        if sum(row.line_total for row in payload.rows) > 2_000_000_000:
            raise HTTPException(400, "Montant de l’import trop élevé.")

        candidates = duplicate_candidates(db, merchant_id, shop_id, groups)
        if candidates and not meaningful(payload.duplicate_justification):
            raise PhotoConflict("business_duplicate", "Ventes similaires déjà présentes. Vérifie puis justifie s’il s’agit de ventes distinctes.", candidates=candidates[:50])

        if payload.affect_stock:
            # A row lock does not refresh an instance already in the identity map.
            # Read committed purchases may have changed stock while this request
            # waited for the merchant lock. Reload ONCE before checks/mutations;
            # refreshing per line would discard pending deltas with autoflush off.
            db.query(ShopInventory).filter(
                ShopInventory.merchant_id == merchant_id,
                ShopInventory.shop_id == shop_id,
                ShopInventory.product_id.in_(sorted(needed)),
            ).order_by(ShopInventory.product_id).populate_existing().with_for_update().all()
            for product_id, quantity in sorted(needed.items()):
                if get_effective_stock(products[product_id], db) < quantity:
                    raise HTTPException(
                        400, "Stock insuffisant pour " + products[product_id].name
                    )

        sale_ids = []

        for group in sorted(groups):
            rows = sorted(groups[group], key=lambda row: row.row_number)
            occurred = datetime.combine(rows[0].sale_date, time.min)
            total = sum(row.line_total for row in rows)
            paid = sum(row.paid_amount for row in rows)
            sale = Sale(
                merchant_id=merchant_id,
                sale_number=allocate_sale_number(db, merchant_id),
                customer_id=rows[0].customer_id,
                total_amount=total,
                paid_amount=paid,
                remaining_amount=total-paid,
                status="paid" if paid == total else "partial" if paid else "credit",
                created_at=occurred,
            )
            db.add(sale)
            db.flush()
            sale_ids.append(sale.id)

            db.add(ShopOperation(
                merchant_id=merchant_id,
                shop_id=shop_id,
                user_id=get_current_user_id(db),
                entity_type="sale",
                entity_id=sale.id,
            ))

            payment = None
            if paid:
                channel = next(
                    row.payment_channel for row in rows if row.paid_amount > 0
                )
                payment = Payment(
                    merchant_id=merchant_id,
                    sale_id=sale.id,
                    customer_id=sale.customer_id,
                    amount=paid,
                    channel=channel,
                    reference="Import photo",
                    paid_at=occurred,
                )
                db.add(payment)
                db.flush()

            for row in rows:
                product = products[row.product_id]
                if payload.affect_stock:
                    adjust_stock(product, -row.quantity, db)
                    db.add(StockMovement(
                        merchant_id=merchant_id,
                        product_id=product.id,
                        movement_type="sale_out",
                        quantity=-row.quantity,
                        reference_type="sale",
                        reference_id=sale.id,
                        note="Import photo validé",
                        created_at=occurred,
                    ))

                item = SaleItem(
                    sale_id=sale.id,
                    product_id=product.id,
                    quantity=row.quantity,
                    unit_price=row.unit_price,
                    unit_cost_snapshot=int(product.purchase_price or 0),
                    line_total=row.line_total,
                    paid_amount=row.paid_amount,
                    remaining_amount=row.line_total-row.paid_amount,
                    status=(
                        "paid" if row.paid_amount == row.line_total
                        else "partial" if row.paid_amount else "credit"
                    ),
                )
                db.add(item)
                db.flush()

                if row.paid_amount:
                    db.add(PaymentAllocation(
                        payment_id=payment.id,
                        sale_item_id=item.id,
                        allocated_amount=row.paid_amount,
                    ))

                db.add(SalePhotoImport(
                    merchant_id=merchant_id,
                    shop_id=shop_id,
                    source_sha256=payload.source_sha256,
                    payload_hash=fingerprint,
                    row_number=row.row_number,
                    sale_id=sale.id,
                    stock_applied=payload.affect_stock,
                ))

            if sale.customer_id is not None:
                customers[sale.customer_id].debt += total-paid

            db.add(TransactionEvent(
                merchant_id=merchant_id,
                entity_type="sale",
                entity_id=sale.id,
                event_type="created",
                amount_signed=total,
                note="Import photo validé",
                created_at=occurred,
            ))

        response = dict(sale_ids=sale_ids, already_imported=False)
        draft.confirmation_hash = fingerprint
        draft.response = response
        draft.confirmed_at = datetime.utcnow()
        draft.audit = {
            "payload": canonical, "user_id": get_current_user_id(db),
            "reconciliation": reconciliation, "duplicate_candidates": candidates,
            "stock_rule": "deduct_current" if payload.affect_stock else "keep_current",
        }
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def meaningful(value):
    return value is not None and len(value.strip()) >= 10


def reconcile_totals(payload, extracted):
    calculated = sum(row.line_total for row in payload.rows)
    issues = []
    original = extracted.get("document_total")
    if payload.document_total is None:
        issues.append("document_total_missing")
    elif payload.document_total != calculated:
        issues.append("document_total_mismatch")
    if original != payload.document_total:
        issues.append("document_total_corrected")
    daily = defaultdict(int)
    for row in payload.rows:
        daily[row.sale_date.isoformat()] += row.line_total
    declared = [item.model_dump(mode="json") for item in payload.daily_totals]
    if len({item["sale_date"] for item in declared}) != len(declared):
        raise PhotoConflict("daily_total_duplicate", "Un seul sous-total déclaré par journée est permis.")
    if declared != extracted.get("daily_totals", []):
        issues.append("daily_totals_corrected")
    for item in declared:
        if item["total"] != daily.get(item["sale_date"], 0):
            issues.append("daily_total_mismatch:" + item["sale_date"])
    if issues and not meaningful(payload.total_justification):
        raise PhotoConflict("total_reconciliation", "Total absent, corrigé ou incohérent : corrige les lignes ou justifie explicitement l’écart.")
    return {"calculated": calculated, "daily_calculated": dict(daily), "issues": issues}


def duplicate_candidates(db, merchant_id, shop_id, groups):
    # Deliberately conservative: same date and a shared product flags a possible
    # recapture even if OCR altered quantity, price, customer or grouping.
    # No unique business fingerprint: identical legitimate sales remain possible.
    dates = {rows[0].sale_date for rows in groups.values()}
    sales = db.query(Sale).join(ShopOperation, (
        (ShopOperation.entity_type == "sale") & (ShopOperation.entity_id == Sale.id)
    )).filter(
        Sale.merchant_id == merchant_id, ShopOperation.merchant_id == merchant_id,
        ShopOperation.shop_id == shop_id,
        func.date(Sale.created_at).in_(list(dates)),
    ).all()
    candidates = []
    for sale in sales:
        items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
        for group, rows in groups.items():
            if sale.created_at.date() != rows[0].sale_date:
                continue
            if not {i.product_id for i in items} & {r.product_id for r in rows}:
                continue
            signature = lambda row: (row.product_id, row.quantity, row.unit_price, row.line_total)
            exact = Counter(map(signature, items)) == Counter(map(signature, rows))
            candidates.append({
                "sale_id": sale.id, "sale_number": sale.reference_number,
                "sale_date": sale.created_at.date().isoformat(), "total_amount": sale.total_amount,
                "group": group, "match": "exact" if exact else "possible",
            })
    return candidates
