from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment

router = APIRouter(tags=["ledger fournisseurs"])


@router.get("/suppliers/{supplier_id}/ledger")
def get_supplier_ledger(supplier_id: int, db: Session = Depends(get_db)):
    """Retourne le ledger complet d’un fournisseur : achats, paiements, dette et lignes ouvertes."""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    purchases = (
        db.query(Purchase)
        .filter(Purchase.supplier_id == supplier_id)
        .order_by(Purchase.id.asc())
        .all()
    )

    supplier_payments = (
        db.query(SupplierPayment)
        .filter(SupplierPayment.supplier_id == supplier_id)
        .order_by(SupplierPayment.id.asc())
        .all()
    )

    purchases_data = []
    open_items = []

    for purchase in purchases:
        items = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase.id).all()

        purchases_data.append(
            {
                "purchase_id": purchase.id,
                "total_amount": purchase.total_amount,
                "paid_amount": purchase.paid_amount,
                "remaining_amount": purchase.remaining_amount,
                "status": purchase.status,
                "items": [
                    {
                        "purchase_item_id": item.id,
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "unit_cost": item.unit_cost,
                        "line_total": item.line_total,
                        "paid_amount": item.paid_amount,
                        "remaining_amount": item.remaining_amount,
                        "status": item.status,
                    }
                    for item in items
                ],
            }
        )

        for item in items:
            if item.remaining_amount > 0 and purchase.status != "cancelled":
                open_items.append(
                    {
                        "purchase_id": purchase.id,
                        "purchase_item_id": item.id,
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "line_total": item.line_total,
                        "paid_amount": item.paid_amount,
                        "remaining_amount": item.remaining_amount,
                        "status": item.status,
                    }
                )

    payments_data = [
        {
            "supplier_payment_id": payment.id,
            "purchase_id": payment.purchase_id,
            "amount": payment.amount,
            "channel": payment.channel,
            "reference": payment.reference,
        }
        for payment in supplier_payments
    ]

    return {
        "supplier": {
            "id": supplier.id,
            "name": supplier.name,
            "phone": supplier.phone,
            "debt": supplier.debt,
        },
        "purchases": purchases_data,
        "payments": payments_data,
        "open_items": open_items,
    }
