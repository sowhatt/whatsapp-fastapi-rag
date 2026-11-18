"""Reserve a scoped key and commit its immutable receipt with the business rows."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select, update
from app.db.tenant import get_current_merchant
from app.models.purchase_request import PurchaseRequest
from app.models.shop import Shop
from app.schemas.purchase import PurchaseRead
from app.services.shop_context_service import get_current_shop_id


def reserve_purchase(db, payload):
    if not payload.idempotency_key:
        raise HTTPException(428, 'Clé idempotency_key obligatoire. Mettez à jour le client achats (contrat v2).')
    merchant_id = get_current_merchant(db)
    if merchant_id is None:
        raise HTTPException(403, 'Contexte commerçant obligatoire')
    shop_scope = get_current_shop_id(db) or 0
    if shop_scope and not db.query(Shop.id).filter(Shop.id == shop_scope, Shop.merchant_id == merchant_id).first():
        raise HTTPException(403, 'Boutique inaccessible')
    data = payload.model_dump(mode='json', exclude={'idempotency_key'})
    if data.get('payment_effective_at') is None: data.pop('payment_effective_at',None)
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    values = dict(merchant_id=merchant_id, shop_scope=shop_scope, operation='purchase.create.v2',
                  request_key=payload.idempotency_key, payload_hash=fingerprint)
    table = PurchaseRequest.__table__
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    elif db.bind.dialect.name == 'sqlite':  # unit tests only; startup still rejects SQLite
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError('Unsupported transaction backend')
    statement = insert(table).values(**values).on_conflict_do_nothing(
        index_elements=['merchant_id', 'shop_scope', 'operation', 'request_key']).returning(table.c.id)
    request_id = db.execute(statement).scalar_one_or_none()
    if request_id is not None:
        return request_id, None
    # ON CONFLICT waits for a competing transaction; this subsequent READ
    # COMMITTED statement sees its committed receipt, or the insert won after rollback.
    row = db.execute(select(table).where(
        table.c.merchant_id == merchant_id, table.c.shop_scope == shop_scope,
        table.c.operation == values['operation'], table.c.request_key == payload.idempotency_key,
    )).mappings().one()
    if row['payload_hash'] != fingerprint:
        raise HTTPException(409, 'Cette clé identifie déjà un achat avec un contenu différent')
    if row['receipt'] is None:
        raise HTTPException(409, 'Reçu incomplet : rapprochement requis')
    return row['id'], PurchaseRead.model_validate(row['receipt'])


def save_receipt(db, request_id, purchase):
    receipt = PurchaseRead.model_validate(purchase).model_dump(mode='json')
    db.execute(update(PurchaseRequest.__table__).where(PurchaseRequest.id == request_id).values(receipt=receipt))
    return PurchaseRead.model_validate(receipt)
