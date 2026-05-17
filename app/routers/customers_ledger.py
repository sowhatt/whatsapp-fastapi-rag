from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.sale import Sale
from app.models.sale_item import SaleItem

router = APIRouter(tags=["ledger clients"])


@router.get("/customers/{customer_id}/ledger")
def get_customer_ledger(customer_id: int, db: Session = Depends(get_db)):
    """Retourne le ledger complet d’un client : ventes, paiements, dette et lignes ouvertes."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Client introuvable")

    sales = (
        db.query(Sale)
        .filter(Sale.customer_id == customer_id)
        .order_by(Sale.id.asc())
        .all()
    )

    payments = (
        db.query(Payment)
        .filter(Payment.customer_id == customer_id)
        .order_by(Payment.id.asc())
        .all()
    )

    sales_data = []
    open_items = []

    for sale in sales:
        items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()

        sales_data.append(
            {
                "sale_id": sale.id,
                "total_amount": sale.total_amount,
                "paid_amount": sale.paid_amount,
                "remaining_amount": sale.remaining_amount,
                "status": sale.status,
                "items": [
                    {
                        "sale_item_id": item.id,
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
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
            if item.remaining_amount > 0 and sale.status != "cancelled":
                open_items.append(
                    {
                        "sale_id": sale.id,
                        "sale_item_id": item.id,
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
            "payment_id": payment.id,
            "sale_id": payment.sale_id,
            "amount": payment.amount,
            "channel": payment.channel,
            "reference": payment.reference,
        }
        for payment in payments
    ]

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "debt": customer.debt,
        },
        "sales": sales_data,
        "payments": payments_data,
        "open_items": open_items,
    }
