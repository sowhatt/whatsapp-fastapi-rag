from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.sale_item import SaleItem
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.models.purchase_item import PurchaseItem

router = APIRouter(tags=["allocations"])


@router.get("/payments/{payment_id}/allocations")
def get_payment_allocations(payment_id: int, db: Session = Depends(get_db)):
    """Retourne le détail d’allocation d’un paiement client sur les lignes de vente."""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement client introuvable")

    allocations = (
        db.query(PaymentAllocation)
        .filter(PaymentAllocation.payment_id == payment_id)
        .order_by(PaymentAllocation.id.asc())
        .all()
    )

    results = []
    for allocation in allocations:
        sale_item = db.query(SaleItem).filter(SaleItem.id == allocation.sale_item_id).first()

        results.append(
            {
                "allocation_id": allocation.id,
                "payment_id": allocation.payment_id,
                "sale_item_id": allocation.sale_item_id,
                "allocated_amount": allocation.allocated_amount,
                "sale_item": None if not sale_item else {
                    "id": sale_item.id,
                    "sale_id": sale_item.sale_id,
                    "product_id": sale_item.product_id,
                    "quantity": sale_item.quantity,
                    "unit_price": sale_item.unit_price,
                    "line_total": sale_item.line_total,
                    "paid_amount": sale_item.paid_amount,
                    "remaining_amount": sale_item.remaining_amount,
                    "status": sale_item.status,
                },
            }
        )

    return {
        "payment": {
            "id": payment.id,
            "sale_id": payment.sale_id,
            "customer_id": payment.customer_id,
            "amount": payment.amount,
            "channel": payment.channel,
            "reference": payment.reference,
        },
        "allocations": results,
    }


@router.get("/supplier-payments/{supplier_payment_id}/allocations")
def get_supplier_payment_allocations(supplier_payment_id: int, db: Session = Depends(get_db)):
    """Retourne le détail d’allocation d’un paiement fournisseur sur les lignes d’achat."""
    supplier_payment = (
        db.query(SupplierPayment)
        .filter(SupplierPayment.id == supplier_payment_id)
        .first()
    )
    if not supplier_payment:
        raise HTTPException(status_code=404, detail="Paiement fournisseur introuvable")

    allocations = (
        db.query(SupplierPaymentAllocation)
        .filter(SupplierPaymentAllocation.supplier_payment_id == supplier_payment_id)
        .order_by(SupplierPaymentAllocation.id.asc())
        .all()
    )

    results = []
    for allocation in allocations:
        purchase_item = db.query(PurchaseItem).filter(PurchaseItem.id == allocation.purchase_item_id).first()

        results.append(
            {
                "allocation_id": allocation.id,
                "supplier_payment_id": allocation.supplier_payment_id,
                "purchase_item_id": allocation.purchase_item_id,
                "allocated_amount": allocation.allocated_amount,
                "purchase_item": None if not purchase_item else {
                    "id": purchase_item.id,
                    "purchase_id": purchase_item.purchase_id,
                    "product_id": purchase_item.product_id,
                    "quantity": purchase_item.quantity,
                    "unit_cost": purchase_item.unit_cost,
                    "line_total": purchase_item.line_total,
                    "paid_amount": purchase_item.paid_amount,
                    "remaining_amount": purchase_item.remaining_amount,
                    "status": purchase_item.status,
                },
            }
        )

    return {
        "supplier_payment": {
            "id": supplier_payment.id,
            "purchase_id": supplier_payment.purchase_id,
            "supplier_id": supplier_payment.supplier_id,
            "amount": supplier_payment.amount,
            "channel": supplier_payment.channel,
            "reference": supplier_payment.reference,
        },
        "allocations": results,
    }
