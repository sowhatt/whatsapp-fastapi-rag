from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerRead

router = APIRouter(tags=["clients"])


@router.get("/customers", response_model=list[CustomerRead])
def list_customers(db: Session = Depends(get_db)):
    """Liste tous les clients."""
    return db.query(Customer).all()


@router.post("/customers", response_model=CustomerRead)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    """Crée un client avec son téléphone et son encours éventuel."""
    customer = Customer(
        name=payload.name,
        phone=payload.phone,
        debt=payload.debt,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/customers/debtors")
def list_customer_debtors(db: Session = Depends(get_db)):
    """Retourne uniquement les clients qui ont une dette en cours."""
    return db.query(Customer).filter(Customer.debt > 0).all()


@router.get("/customers/{customer_id}/debt")
def get_customer_debt(customer_id: int, db: Session = Depends(get_db)):
    """Retourne la dette totale d’un client précis."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Client introuvable")

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "debt": customer.debt,
    }
