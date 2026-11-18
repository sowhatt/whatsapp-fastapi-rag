import hashlib
import json
from collections import defaultdict
from datetime import datetime, time, timezone
from fastapi import HTTPException
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
from app.models.stock_movement import StockMovement
from app.models.transaction_event import TransactionEvent
from app.rbac import has_permission
from app.routers.sales import allocate_sale_number
from app.services.shop_context_service import (
    adjust_stock, get_current_shop_id,
    get_current_user_id, get_effective_stock,
)


def confirm_photo_sales(payload, db):
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
    if payload.document_date > datetime.now(timezone.utc).date():
        raise HTTPException(400, "La date de vente ne peut pas être future.")

    canonical = payload.model_dump(mode="json", exclude={"confirmed"})
    canonical["rows"].sort(key=lambda row: row["row_number"])
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    try:
        db.query(Merchant).filter(
            Merchant.id == merchant_id
        ).with_for_update().one()

        previous = db.query(SalePhotoImport).filter(
            SalePhotoImport.merchant_id == merchant_id,
            SalePhotoImport.shop_id == shop_id,
            SalePhotoImport.source_sha256 == payload.source_sha256,
        ).all()
        if previous:
            if any(row.payload_hash != fingerprint for row in previous):
                raise HTTPException(
                    409,
                    "Cette photo a déjà été importée avec des données différentes.",
                )
            return dict(
                sale_ids=sorted({row.sale_id for row in previous}),
                already_imported=True,
            )

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
                ).with_for_update().first()
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

        if payload.affect_stock:
            for product_id, quantity in sorted(needed.items()):
                if get_effective_stock(products[product_id], db) < quantity:
                    raise HTTPException(
                        400, "Stock insuffisant pour " + products[product_id].name
                    )

        occurred = datetime.combine(payload.document_date, time.min)
        sale_ids = []

        for group in sorted(groups):
            rows = sorted(groups[group], key=lambda row: row.row_number)
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

        db.commit()
        return dict(sale_ids=sale_ids, already_imported=False)
    except Exception:
        db.rollback()
        raise
