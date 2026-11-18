import hashlib,json
from datetime import datetime
from typing import Literal
from pydantic import BaseModel,Field,field_validator
from fastapi import HTTPException
from sqlalchemy import func,text
from app.models.customer_refund import SaleCancellation,CustomerRefund,RefundAllocation
from app.models.payment import Payment
from app.models.transaction_event import TransactionEvent
from app.services.payment_transactions import lock_payment_target
from app.services.finance_time import aware
from app.services.shop_context_service import get_current_shop_id
from app.db.tenant import get_current_merchant

class RefundCreate(BaseModel):
    sale_id: int
    amount: int = Field(gt=0)
    channel: str = Field(min_length=1,max_length=30)
    effective_at: datetime
    reference: str | None = Field(default=None,max_length=100)
    idempotency_key: str = Field(min_length=8,max_length=128,pattern=r'^[A-Za-z0-9._:-]+$')
    confirmed: Literal[True]
    _date=field_validator('effective_at')(aware)

def receipt(row):
    return dict(id=row.id,sale_id=row.sale_id,amount=row.amount,channel=row.channel,
        effective_at=row.effective_at.isoformat(),recorded_at=row.recorded_at.isoformat(),reference=row.reference)

def due_rows(db):
    merchant,shop=get_current_merchant(db),get_current_shop_id(db)
    rows=db.query(SaleCancellation).filter(SaleCancellation.merchant_id==merchant,SaleCancellation.shop_id==shop).order_by(SaleCancellation.sale_id).all()
    return [dict(sale_id=r.sale_id,receivable_waived=r.receivable_waived,refundable_amount=r.refundable_amount,
        remaining=r.refundable_amount-int(db.query(func.coalesce(func.sum(CustomerRefund.amount),0)).filter(CustomerRefund.sale_id==r.sale_id).scalar()),
        reason=r.reason,cancelled_at=r.cancelled_at.isoformat(),actor_user_id=r.actor_user_id) for r in rows]

def create_refund(db,payload):
    merchant,shop=get_current_merchant(db),get_current_shop_id(db)
    actor=db.info.get('pwa_user_id')
    if not merchant or not shop or not actor:raise HTTPException(403,'Contexte utilisateur et boutique requis')
    fingerprint=hashlib.sha256(json.dumps(payload.model_dump(mode='json',exclude={'idempotency_key'}),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    try:
        db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':f'refund:{merchant}:{shop}:{payload.idempotency_key}'})
        old=db.query(CustomerRefund).filter_by(merchant_id=merchant,shop_id=shop,request_key=payload.idempotency_key).first()
        if old:
            if old.payload_hash!=fingerprint:raise HTTPException(409,'Clé de remboursement déjà utilisée avec un autre contenu')
            result=receipt(old);db.rollback();return result
        _,sale,_=lock_payment_target(db,payload.sale_id)
        cancellation=db.query(SaleCancellation).filter_by(sale_id=sale.id,merchant_id=merchant,shop_id=shop).populate_existing().with_for_update().first()
        if sale.status!='cancelled' or cancellation is None:raise HTTPException(409,'Annulation avec restitution due requise')
        paid=int(db.query(func.coalesce(func.sum(CustomerRefund.amount),0)).filter_by(sale_id=sale.id).scalar())
        if payload.amount>cancellation.refundable_amount-paid:raise HTTPException(400,'Le remboursement dépasse la restitution restante')
        payments=db.query(Payment).filter(Payment.sale_id==sale.id).order_by(Payment.id).with_for_update().all()
        refund=CustomerRefund(merchant_id=merchant,shop_id=shop,sale_id=sale.id,actor_user_id=actor,
            amount=payload.amount,channel=payload.channel,effective_at=payload.effective_at,reference=payload.reference,
            request_key=payload.idempotency_key,payload_hash=fingerprint)
        db.add(refund);db.flush();remaining=payload.amount
        for payment in payments:
            used=int(db.query(func.coalesce(func.sum(RefundAllocation.amount),0)).filter_by(payment_id=payment.id).scalar())
            part=min(remaining,payment.amount-used)
            if part>0:db.add(RefundAllocation(refund_id=refund.id,payment_id=payment.id,amount=part));remaining-=part
        if remaining:raise HTTPException(409,'Paiements d’origine insuffisants : rapprochement requis')
        db.add(TransactionEvent(merchant_id=merchant,entity_type='sale',entity_id=sale.id,
            event_type='customer_refund',amount_signed=-payload.amount,note='Remboursement confirmé : '+payload.channel))
        db.flush();result=receipt(refund);db.commit();return result
    except Exception:db.rollback();raise
