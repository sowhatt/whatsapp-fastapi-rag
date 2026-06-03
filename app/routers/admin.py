from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["admin"])


@router.post("/admin/truncate-db")
def truncate_db(db: Session = Depends(get_db)):
    try:
        db.execute(
            text("""
                TRUNCATE TABLE
                    payment_allocations,
                    supplier_payment_allocations,
                    payments,
                    supplier_payments,
                    sale_items,
                    purchase_items,
                    sales,
                    purchases,
                    stock_movements,
                    transaction_events,
                    financial_entries,
                    customers,
                    suppliers,
                    products
                RESTART IDENTITY CASCADE;
            """)
        )
        db.commit()
        return {"message": "Base vidée avec succès"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))