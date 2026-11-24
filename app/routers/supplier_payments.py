from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.models.shop_operation import ShopOperation
from app.rbac import require_permission
from app.schemas.supplier_payment import SupplierPaymentCreate, SupplierPaymentRead
from app.services.shop_context_service import get_current_shop_id

from app.services.purchasing_integrity_service import execute_write, suppliers_query, purchases_query, payment_time, ensure_supplier_balance

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
    request: Request = None,
):
    return execute_write(payload, db, kind="payment", permission="supplier_payment.create",
                         operation=lambda: _create_supplier_payment(payload, db), schema=SupplierPaymentRead,
                         http=request is not None)


def _create_supplier_payment(payload, db):
    purchase = purchases_query(db).filter(Purchase.id == payload.purchase_id).populate_existing().with_for_update(of=Purchase).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Achat introuvable")

    if payload.supplier_id is None:
        raise HTTPException(status_code=400, detail="L'identifiant du fournisseur est obligatoire")

    supplier = suppliers_query(db).filter(Supplier.id == payload.supplier_id).populate_existing().with_for_update().first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    ensure_supplier_balance(supplier, db)

    if purchase.supplier_id != payload.supplier_id:
        raise HTTPException(
            status_code=400,
            detail="Le fournisseur ne correspond pas à celui de cet achat",
        )

    if purchase.status == "cancelled":
        raise HTTPException(409, "Achat annulé.")
    if payload.channel not in {"cash", "mobile_money", "card", "bank_transfer", "moov_money", "mtn_momo", "bank"}:
        raise HTTPException(400, "Mode de paiement invalide.")
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
        paid_at=payment_time(payload.paid_at),
    )
    db.add(supplier_payment)
    db.flush()

    remaining_to_allocate = payload.amount

    purchase_items = (
        db.query(PurchaseItem)
        .filter(
            PurchaseItem.purchase_id == purchase.id,
        )
        .order_by(PurchaseItem.id.asc())
        .populate_existing().with_for_update()
        .all()
    )

    if (
        sum(item.line_total for item in purchase_items) != purchase.total_amount
        or sum(item.paid_amount for item in purchase_items) != purchase.paid_amount
        or sum(item.remaining_amount for item in purchase_items) != purchase.remaining_amount
        or any(item.paid_amount < 0 or item.remaining_amount < 0
               or item.paid_amount + item.remaining_amount != item.line_total for item in purchase_items)
    ):
        raise HTTPException(409, "Les lignes d’achat et le solde sont incohérents. Rapprochement requis.")

    for item in purchase_items:
        if remaining_to_allocate <= 0:
            break
        if item.remaining_amount <= 0:
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

    if remaining_to_allocate:
        raise HTTPException(409, "Les lignes d’achat ne correspondent pas au reste dû. Rapprochement requis.")
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

    return supplier_payment
