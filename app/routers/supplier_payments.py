from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.schemas.supplier_payment import SupplierPaymentCreate, SupplierPaymentRead

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
def create_supplier_payment(payload: SupplierPaymentCreate, db: Session = Depends(get_db)):
    """Enregistre un paiement fournisseur et l’impute en FIFO sur les lignes d’achat."""
    purchase = db.query(Purchase).filter(Purchase.id == payload.purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Achat introuvable")

    if payload.supplier_id is None:
        raise HTTPException(status_code=400, detail="L'identifiant du fournisseur est obligatoire")

    supplier = db.query(Supplier).filter(Supplier.id == payload.supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    if purchase.supplier_id != payload.supplier_id:
        raise HTTPException(
            status_code=400,
            detail="Le fournisseur ne correspond pas à celui de cet achat",
        )

    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Le montant du paiement doit être supérieur à zéro")

    if payload.amount > purchase.remaining_amount:
        raise HTTPException(status_code=400, detail="Le montant du paiement dépasse le reste dû")

    supplier_payment = SupplierPayment(
        purchase_id=payload.purchase_id,
        supplier_id=payload.supplier_id,
        amount=payload.amount,
        channel=payload.channel,
        reference=payload.reference,
    )
    db.add(supplier_payment)
    db.flush()

    remaining_to_allocate = payload.amount

    purchase_items = (
        db.query(PurchaseItem)
        .filter(
            PurchaseItem.purchase_id == purchase.id,
            PurchaseItem.remaining_amount > 0,
        )
        .order_by(PurchaseItem.id.asc())
        .all()
    )

    for item in purchase_items:
        if remaining_to_allocate <= 0:
            break

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

    purchase.paid_amount += payload.amount
    purchase.remaining_amount -= payload.amount

    if purchase.remaining_amount == 0:
        purchase.status = "paid"
    else:
        purchase.status = "partial"

    supplier.debt = max(0, supplier.debt - payload.amount)

    add_event(
        db,
        "purchase",
        purchase.id,
        "supplier_payment_added",
        amount_signed=-payload.amount,
        note=f"Paiement fournisseur par {payload.channel}",
    )

    db.commit()
    db.refresh(supplier_payment)
    return supplier_payment
