from datetime import datetime, timezone, timedelta
from app.services.supplier_payment_transactions import reserve_supplier_payment, save_supplier_receipt
from app.services.purchase_transactions import purchase_query
from app.services.shop_context_service import get_current_shop_id
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.purchase_item import PurchaseItem
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.rbac import require_permission
from app.schemas.supplier_payment import SupplierPaymentCreate, SupplierPaymentRead

from app.services.purchase_transactions import lock_purchase, validate_purchase_balances

router = APIRouter(tags=["paiements fournisseurs"])


def add_event(
    db: Session,
    entity_type: str,
    entity_id: int,
    event_type: str,
    amount_signed: int | None = None,
    note: str | None = None,
):
    from app.models.transaction_event import TransactionEvent

    db.add(
        TransactionEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            amount_signed=amount_signed,
            note=note,
        )
    )


@router.post("/supplier-payments", response_model=SupplierPaymentRead)
def create_supplier_payment(
    payload: SupplierPaymentCreate,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("supplier_payment.create")),
):
    try:
        if purchase_query(db).filter_by(id=payload.purchase_id).first() is None:
            raise HTTPException(404, 'Achat introuvable')
        request_id, replay = reserve_supplier_payment(db, payload)
        if replay is not None:
            db.commit()
            return replay
        # No new backdating permission. Replays bypass this first-send window.
        if payload.effective_at and abs(datetime.now(timezone.utc) - payload.effective_at) > timedelta(minutes=5):
            raise HTTPException(422, 'Le règlement doit être déclaré maintenant ; datation passée non autorisée')
        payment = _create_supplier_payment(payload, db)
        db.flush()
        receipt = SupplierPaymentRead.model_validate(payment).model_copy(update={
            'currency_code': purchase_query(db).filter_by(id=payload.purchase_id).one().currency_code, 'idempotency_key': payload.idempotency_key, 'shop_id': get_current_shop_id(db),
            'allocations': [{'purchase_item_id': a.purchase_item_id, 'amount': a.allocated_amount} for a in
                db.query(SupplierPaymentAllocation).filter_by(supplier_payment_id=payment.id).order_by(SupplierPaymentAllocation.id).all()]})
        save_supplier_receipt(db, request_id, receipt)
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise


def _create_supplier_payment(payload, db):
    """Enregistre un paiement fournisseur et l’impute en FIFO sur les lignes d’achat."""
    supplier, purchase = lock_purchase(db, payload.purchase_id)
    if purchase.status == "cancelled":
        raise HTTPException(400, "Cet achat est annulé")

    if supplier is None:
        raise HTTPException(400, "Cet achat comptant sans fournisseur est déjà intégralement payé")

    if purchase.supplier_id != payload.supplier_id:
        raise HTTPException(
            status_code=400,
            detail="Le fournisseur ne correspond pas à celui de cet achat",
        )

    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Le montant du paiement doit être supérieur à zéro")

    if payload.amount > purchase.remaining_amount:
        raise HTTPException(status_code=400, detail="Le montant du paiement dépasse le reste dû")

    purchase_items = (
        db.query(PurchaseItem)
        .filter(
            PurchaseItem.purchase_id == purchase.id,
        )
        .order_by(PurchaseItem.id.asc())
        .populate_existing()
        .with_for_update()
        .all()
    )

    validate_purchase_balances(db, purchase, purchase_items)

    supplier_payment = SupplierPayment(
        purchase_id=payload.purchase_id,
        supplier_id=payload.supplier_id,
        amount=payload.amount,
        channel=payload.channel,
        reference=payload.reference,
        effective_at=payload.effective_at or datetime.now(timezone.utc),
        effective_at_source='declared_now' if payload.effective_at else 'server_now',
    )
    db.add(supplier_payment)
    db.flush()

    remaining_to_allocate = payload.amount

    for item in purchase_items:
        if remaining_to_allocate <= 0:
            break

        if item.remaining_amount == 0:
            continue
        alloc_amount = min(remaining_to_allocate, item.remaining_amount)

        item.paid_amount += alloc_amount
        item.remaining_amount -= alloc_amount

        if item.remaining_amount == 0:
            item.status = "paid"
        else:
            item.status = "partial"

        db.add(
            SupplierPaymentAllocation(
                supplier_payment_id=supplier_payment.id,
                purchase_item_id=item.id,
                allocated_amount=alloc_amount,
            )
        )

        remaining_to_allocate -= alloc_amount

    if remaining_to_allocate != 0:
        raise HTTPException(409, "Lignes d'achat incohérentes : rapprochement requis")

    purchase.paid_amount += payload.amount
    purchase.remaining_amount -= payload.amount

    if purchase.remaining_amount == 0:
        purchase.status = "paid"
    else:
        purchase.status = "partial"

    supplier.debt -= payload.amount
    if supplier.debt < 0:
        raise HTTPException(409, "Dette fournisseur incohérente : rapprochement requis")

    add_event(
        db,
        "purchase",
        purchase.id,
        "supplier_payment_added",
        amount_signed=-payload.amount,
        note=f"Paiement fournisseur par {payload.channel}",
    )

    db.flush()
    validate_purchase_balances(db, purchase, purchase_items)
    return supplier_payment
