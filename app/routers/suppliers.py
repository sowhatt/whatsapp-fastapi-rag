from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierRead

router = APIRouter(tags=["fournisseurs"])


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


@router.get("/suppliers", response_model=list[SupplierRead])
def list_suppliers(db: Session = Depends(get_db)):
    """Liste tous les fournisseurs."""
    return db.query(Supplier).all()


@router.post("/suppliers", response_model=SupplierRead)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    """Crée un fournisseur."""
    existing = db.query(Supplier).filter(Supplier.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce fournisseur existe déjà")

    supplier = Supplier(
        name=payload.name,
        phone=payload.phone,
        debt=payload.debt,
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)

    add_event(
        db,
        "supplier",
        supplier.id,
        "created",
        note=f"Fournisseur {supplier.name} créé",
    )
    db.commit()

    return supplier


@router.get("/suppliers/{supplier_id}/debt")
def get_supplier_debt(supplier_id: int, db: Session = Depends(get_db)):
    """Retourne la dette totale d’un fournisseur précis."""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    return {
        "supplier_id": supplier.id,
        "name": supplier.name,
        "debt": supplier.debt,
    }
