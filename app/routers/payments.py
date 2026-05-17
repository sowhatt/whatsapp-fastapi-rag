from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.schemas.payment import PaymentCreate, PaymentRead

router = APIRouter(tags=["paiements clients"])


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


@router.post("/payments", response_model=PaymentRead)
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)):
    """Enregistre un paiement client et l’impute en FIFO sur les lignes de vente."""
    sale = db.query(Sale).filter(Sale.id == payload.sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Vente introuvable")

    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Le montant du paiement doit être supérieur à zéro")

    if payload.amount > sale.remaining_amount:
        raise HTTPException(status_code=400, detail="Le montant du paiement dépasse le reste dû")

    payment = Payment(
        sale_id=payload.sale_id,
        customer_id=payload.customer_id,
        amount=payload.amount,
        channel=payload.channel,
        reference=payload.reference,
    )
    db.add(payment)
    db.flush()

    remaining_to_allocate = payload.amount

    sale_items = (
        db.query(SaleItem)
        .filter(
            SaleItem.sale_id == sale.id,
            SaleItem.remaining_amount > 0,
        )
        .order_by(SaleItem.id.asc())
        .all()
    )

    for item in sale_items:
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
            PaymentAllocation(
                payment_id=payment.id,
                sale_item_id=item.id,
                allocated_amount=alloc_amount,
            )
        )

        remaining_to_allocate -= alloc_amount

    sale.paid_amount += payload.amount
    sale.remaining_amount -= payload.amount

    if sale.remaining_amount == 0:
        sale.status = "paid"
    else:
        sale.status = "partial"

    if payload.customer_id:
        customer = db.query(Customer).filter(Customer.id == payload.customer_id).first()
        if customer:
            customer.debt = max(0, customer.debt - payload.amount)

    add_event(
        db,
        "sale",
        sale.id,
        "payment_added",
        amount_signed=payload.amount,
        note=f"Paiement client par {payload.channel}",
    )

    db.commit()
    db.refresh(payment)
    return payment
