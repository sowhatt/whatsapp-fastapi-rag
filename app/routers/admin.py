from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

import os

from fastapi import Header, HTTPException


def _verifier_token_admin(x_admin_token: str) -> None:
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Accès refusé")


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