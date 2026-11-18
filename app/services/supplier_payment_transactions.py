"""Persistent supplier request journal; reservation and receipt share the payment transaction."""
import hashlib, json
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from app.db.tenant import get_current_merchant
from app.services.shop_context_service import get_current_shop_id
from app.models.supplier_payment_request import SupplierPaymentRequest
from app.schemas.supplier_payment import SupplierPaymentRead

def reserve_supplier_payment(db, payload):
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
    table = SupplierPaymentRequest.__table__
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
    return row['id'], SupplierPaymentRead.model_validate(row['receipt'])


def save_supplier_receipt(db, request_id, receipt):
    if request_id is not None:
        db.execute(update(SupplierPaymentRequest.__table__).where(SupplierPaymentRequest.id == request_id)
                   .values(payment_id=receipt.id, receipt=receipt.model_dump(mode='json')))
