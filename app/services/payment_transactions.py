"""Payment locks: scoped request key -> customer -> sale -> ordered sale items.

READ COMMITTED is required. Locked ORM reads refresh the identity map; an older
pre-validation read must never authorize a payment. No function commits here.
"""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from app.db.tenant import get_current_merchant
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.shop_operation import ShopOperation
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.payment_request import PaymentRequest
from app.schemas.payment import PaymentRead
from app.services.shop_context_service import get_current_shop_id


def sale_query(db):
    query = db.query(Sale)
    shop_id = get_current_shop_id(db)
    if shop_id is not None:
        query = query.filter(db.query(ShopOperation.id).filter(
            ShopOperation.entity_type == 'sale', ShopOperation.entity_id == Sale.id,
            ShopOperation.shop_id == shop_id,
            ShopOperation.merchant_id == Sale.merchant_id,
        ).exists())
    return query


def lock_payment_target(db, sale_id):
    # Read only immutable ownership scalars, never an unlocked balance.
    owner = sale_query(db).filter(Sale.id == sale_id).with_entities(Sale.customer_id, Sale.merchant_id).first()
    if owner is None:
        raise HTTPException(404, 'Vente introuvable')
    with db.no_autoflush:
        customer = None
        if owner.customer_id is not None:
            customer = (db.query(Customer).filter(Customer.id == owner.customer_id,
                        Customer.merchant_id == owner.merchant_id)
                        .populate_existing().with_for_update(of=Customer).first())
            if customer is None:
                raise HTTPException(409, 'Client de la vente introuvable : rapprochement requis')
        sale = (sale_query(db).filter(Sale.id == sale_id)
                .populate_existing().with_for_update(of=Sale).first())
        if sale is None:
            raise HTTPException(404, 'Vente introuvable')
        if sale.customer_id != owner.customer_id:
            raise HTTPException(409, 'Client de la vente modifié : recommencer')
        items = (db.query(SaleItem).filter(SaleItem.sale_id == sale.id)
                 .order_by(SaleItem.id).populate_existing()
                 .with_for_update(of=SaleItem).all())
    return customer, sale, items


def validate_balances(db, sale, items):
    totals = (sum(i.line_total for i in items), sum(i.paid_amount for i in items),
              sum(i.remaining_amount for i in items))
    expected = (sale.total_amount, sale.paid_amount, sale.remaining_amount)
    payments = (db.query(Payment.id, Payment.amount,
                        func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
                .outerjoin(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
                .filter(Payment.sale_id == sale.id)
                .group_by(Payment.id, Payment.amount).all())
    wrong_target = (db.query(PaymentAllocation.id)
                    .join(Payment, Payment.id == PaymentAllocation.payment_id)
                    .join(SaleItem, SaleItem.id == PaymentAllocation.sale_item_id)
                    .filter(Payment.sale_id == sale.id, SaleItem.sale_id != sale.id).first())
    allocated = dict(db.query(PaymentAllocation.sale_item_id,
                     func.sum(PaymentAllocation.allocated_amount))
                     .join(SaleItem, SaleItem.id == PaymentAllocation.sale_item_id)
                     .filter(SaleItem.sale_id == sale.id)
                     .group_by(PaymentAllocation.sale_item_id).all())
    if (not items or totals != expected or wrong_target
            or sale.total_amount != sale.paid_amount + sale.remaining_amount
            or sum(amount for _, amount, _ in payments) != sale.paid_amount
            or any(amount != allocation for _, amount, allocation in payments)
            or any(i.paid_amount < 0 or i.remaining_amount < 0
                   or i.line_total != i.paid_amount + i.remaining_amount
                   or allocated.get(i.id, 0) != i.paid_amount for i in items)):
        raise HTTPException(409, 'Soldes ou allocations incohérents : rapprochement requis')


def reserve_payment(db, payload):
    if payload.idempotency_key is None:
        # Backward compatibility: unkeyed calls remain distinct payments.
        return None, None
    merchant_id = get_current_merchant(db)
    if merchant_id is None:
        raise HTTPException(403, 'Contexte commerçant obligatoire pour une clé de règlement')
    scope = get_current_shop_id(db) or 0
    canonical = payload.model_dump(mode='json', exclude={'idempotency_key'})
    if canonical.get('effective_at') is None:
        canonical.pop('effective_at', None)  # keep historical request fingerprints
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True,
                                separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    table = PaymentRequest.__table__
    values = dict(merchant_id=merchant_id, shop_scope=scope,
                  request_key=payload.idempotency_key, payload_hash=fingerprint)
    # A competing insert waits for commit/rollback; never commits a reservation alone.
    request_id = db.execute(insert(table).values(**values).on_conflict_do_nothing(
        index_elements=['merchant_id', 'shop_scope', 'request_key']).returning(table.c.id)).scalar_one_or_none()
    if request_id is not None:
        return request_id, None
    row = db.execute(select(table).where(table.c.merchant_id == merchant_id,
        table.c.shop_scope == scope, table.c.request_key == payload.idempotency_key)).mappings().one()
    if row['payload_hash'] != fingerprint:
        raise HTTPException(409, 'Cette clé identifie déjà un règlement avec un contenu différent')
    if row['receipt'] is None or row['payment_id'] is None:
        raise HTTPException(409, 'Reçu incomplet : rapprochement requis')
    return row['id'], PaymentRead.model_validate(row['receipt'])


def save_receipt(db, request_id, receipt):
    if request_id is not None:
        db.execute(update(PaymentRequest.__table__).where(PaymentRequest.id == request_id)
                   .values(payment_id=receipt.id, receipt=receipt.model_dump(mode='json')))
