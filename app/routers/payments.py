from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.transaction_event import TransactionEvent
from app.schemas.payment import PaymentCreate, PaymentRead
from app.rbac import require_permission
from app.services.payment_transactions import (
    sale_query, lock_payment_target, validate_balances, reserve_payment, save_receipt,
)

router = APIRouter(tags=["paiements clients"])


def apply_payment(payload: PaymentCreate, db: Session):
    """Apply under the caller transaction; never release locks or commit."""
    # Verify current target visibility before returning even an immutable receipt.
    if sale_query(db).filter_by(id=payload.sale_id).first() is None:
        raise HTTPException(404, 'Vente introuvable')
    request_id, replay = reserve_payment(db, payload)
    if replay is not None:
        return replay
    customer, sale, items = lock_payment_target(db, payload.sale_id)
    if sale.status == 'cancelled':
        raise HTTPException(400, 'Cette vente est annulée')
    if payload.customer_id is not None and payload.customer_id != sale.customer_id:
        raise HTTPException(400, 'Le client ne correspond pas à la vente')
    validate_balances(db, sale, items)
    if payload.amount <= 0:
        raise HTTPException(400, 'Le montant du paiement doit être supérieur à zéro')
    if payload.amount > sale.remaining_amount:
        raise HTTPException(400, 'Le montant du paiement dépasse le reste dû')
    if customer is not None and customer.debt < payload.amount:
        raise HTTPException(409, 'Dette client incohérente : rapprochement requis')

    payment = Payment(merchant_id=sale.merchant_id, sale_id=sale.id,
                      customer_id=sale.customer_id, amount=payload.amount,
                      channel=payload.channel, reference=payload.reference,
                      effective_at=payload.effective_at or datetime.now(timezone.utc))
    db.add(payment)
    db.flush()
    remaining = payload.amount
    for item in items:
        allocated = min(remaining, item.remaining_amount)
        if allocated <= 0:
            continue
        item.paid_amount += allocated
        item.remaining_amount -= allocated
        item.status = 'paid' if item.remaining_amount == 0 else 'partial'
        db.add(PaymentAllocation(payment_id=payment.id, sale_item_id=item.id,
                                 allocated_amount=allocated))
        remaining -= allocated
    if remaining:
        raise HTTPException(409, 'Imputation incomplète : rapprochement requis')
    sale.paid_amount += payload.amount
    sale.remaining_amount -= payload.amount
    sale.status = 'paid' if sale.remaining_amount == 0 else 'partial'
    if customer is not None:
        customer.debt -= payload.amount
    db.add(TransactionEvent(merchant_id=sale.merchant_id, entity_type='sale',
           entity_id=sale.id, event_type='payment_added', amount_signed=payload.amount,
           note=f'Paiement client par {payload.channel}'))
    db.flush()
    validate_balances(db, sale, items)
    # Serialize before committing; return this immutable snapshot, not a refresh
    # of an ORM object after another transaction may already have changed it.
    from app.services.shop_context_service import get_current_shop_id
    receipt = PaymentRead.model_validate(payment).model_copy(update={
        'currency_code': sale.currency_code, 'idempotency_key': payload.idempotency_key, 'shop_id': get_current_shop_id(db),
        'effective_at_source': 'declared' if payload.effective_at else 'server_now',
        'allocations': [{'sale_item_id': a.sale_item_id, 'amount': a.allocated_amount} for a in
            db.query(PaymentAllocation).filter_by(payment_id=payment.id).order_by(PaymentAllocation.id).all()]})
    save_receipt(db, request_id, receipt)
    return receipt

@router.post("/payments", response_model=PaymentRead,
             dependencies=[Depends(require_permission("payment.create"))])
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)):
    try:
        receipt = apply_payment(payload, db)
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise

# Explicit capability used by the existing multi-sale orchestrator.
create_payment.transactional = apply_payment
