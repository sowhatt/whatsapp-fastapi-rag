"""Shared lock order: merchant -> purchase/supplier -> products -> inventory.

HTTP writes always require a shop and client UUID. Legacy internal callers can
omit the UUID; they still participate in locking and atomic rollback.
"""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func
from app.db.tenant import get_current_merchant
from app.models.merchant import Merchant
from app.models.purchase import Purchase
from app.models.purchasing_receipt import PurchasingReceipt
from app.models.shop import Shop
from app.models.shop_operation import ShopOperation
from app.models.supplier import Supplier
from app.rbac import has_permission
from app.services.shop_context_service import get_current_shop_id, get_current_user_id


def _require_active_pwa_shop(db):
    if "pwa_shop_id" in db.info and not get_current_shop_id(db):
        raise HTTPException(409, "Sélectionne une boutique.")


def suppliers_query(db):
    _require_active_pwa_shop(db)
    query = db.query(Supplier)
    merchant_id = get_current_merchant(db)
    if merchant_id is not None:
        query = query.filter(Supplier.merchant_id == merchant_id)
    shop_id = get_current_shop_id(db)
    if shop_id is not None:
        query = query.filter(Supplier.shop_id == shop_id)
    return query


def purchases_query(db):
    _require_active_pwa_shop(db)
    query = db.query(Purchase)
    merchant_id, shop_id = get_current_merchant(db), get_current_shop_id(db)
    if merchant_id is not None:
        query = query.filter(Purchase.merchant_id == merchant_id)
    if shop_id is not None:
        query = query.join(ShopOperation, (ShopOperation.entity_type == 'purchase') &
                          (ShopOperation.entity_id == Purchase.id)).filter(
            ShopOperation.shop_id == shop_id, ShopOperation.merchant_id == merchant_id)
    return query


def payment_time(value):
    now = datetime.now(timezone.utc)
    if value is None:
        return now.replace(tzinfo=None)
    if value.tzinfo is None:
        raise HTTPException(422, 'La date de paiement doit préciser son fuseau horaire.')
    value = value.astimezone(timezone.utc)
    if value > now:
        raise HTTPException(422, 'Le paiement ne peut pas être daté dans le futur.')
    return value.replace(tzinfo=None)


def execute_write(payload, db, *, kind, permission, operation, schema, http=False):
    try:
        merchant_id, shop_id = get_current_merchant(db), get_current_shop_id(db)
        role = db.info.get('pwa_role')
        if http or role is not None:
            if merchant_id is None:
                raise HTTPException(401, 'Authentification requise.')
            if not has_permission(role, permission):
                raise HTTPException(403, 'Permission insuffisante.')
        key = getattr(payload, 'idempotency_key', None)
        requested_shop = getattr(payload, 'shop_id', None)
        if http or key is not None or (role is not None and kind != "cancel_purchase"):
            if not key or not shop_id or requested_shop != shop_id:
                raise HTTPException(409, 'Clé de confirmation et boutique active requises.')
        if shop_id is not None:
            if not db.query(Shop).filter_by(id=shop_id, merchant_id=merchant_id).first():
                raise HTTPException(403, 'Boutique inaccessible.')
        if db.get_bind().dialect.name == 'postgresql' and db.connection().get_isolation_level() != 'READ COMMITTED':
            raise HTTPException(503, 'Les écritures achats nécessitent READ COMMITTED.')
        if merchant_id is not None:
            db.query(Merchant).filter_by(id=merchant_id).with_for_update().one()
        fingerprint = None
        if key:
            canonical = payload.model_dump(mode='json', exclude={'idempotency_key'})
            fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            receipt = db.query(PurchasingReceipt).filter_by(merchant_id=merchant_id, key=str(key)).populate_existing().first()
            if receipt:
                if receipt.shop_id != shop_id or receipt.kind != kind or receipt.payload_hash != fingerprint:
                    raise HTTPException(409, 'Cette clé a déjà été utilisée avec un autre contenu ou une autre boutique.')
                result = schema.model_validate(receipt.response)
                db.commit()
                return result
        entity = operation()
        db.flush()
        if key:
            result = schema.model_validate(entity)
            db.add(PurchasingReceipt(
                merchant_id=merchant_id, key=str(key), shop_id=shop_id, kind=kind,
                payload_hash=fingerprint, response=result.model_dump(mode='json'),
                user_id=get_current_user_id(db),
            ))
        else:
            result = entity
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def ensure_supplier_balance(supplier, db):
    if supplier is None or get_current_shop_id(db) is None:
        return
    balance = purchases_query(db).filter(
        Purchase.supplier_id == supplier.id, Purchase.status != 'cancelled'
    ).with_entities(func.coalesce(func.sum(Purchase.remaining_amount), 0)).scalar()
    if int(supplier.debt or 0) != int(balance):
        raise HTTPException(409, 'Dette fournisseur incohérente : rapprochement requis avant écriture.')
