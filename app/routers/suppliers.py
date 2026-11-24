from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import get_current_merchant
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierRead
from app.rbac import require_permission

from app.services.purchasing_integrity_service import execute_write, suppliers_query
from app.services.shop_context_service import get_current_shop_id

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
def list_suppliers(
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("supplier.read")),
):
    """Liste tous les fournisseurs."""
    return suppliers_query(db).order_by(Supplier.name, Supplier.id).all()


@router.post("/suppliers", response_model=SupplierRead)
def create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("supplier.create")),
    request: Request = None,
):
    return execute_write(payload, db, kind="supplier", permission="supplier.create",
                         operation=lambda: _create_supplier(payload, db), schema=SupplierRead,
                         http=request is not None)


def _create_supplier(payload, db):
    """Crée un fournisseur."""
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(400, "Nom du fournisseur requis.")
    if get_current_shop_id(db) is not None and payload.debt:
        raise HTTPException(400, "Enregistre la dette par un achat avec échéance.")
    if get_current_shop_id(db) is not None and db.query(Supplier).filter(
        Supplier.merchant_id == get_current_merchant(db), Supplier.shop_id.is_(None),
        Supplier.name.ilike(name),
    ).first():
        raise HTTPException(409, "Ce fournisseur historique doit être rattaché à une boutique avant réutilisation.")
    existing = suppliers_query(db).filter(Supplier.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce fournisseur existe déjà")

    supplier = Supplier(
        name=name,
        shop_id=get_current_shop_id(db),
        phone=payload.phone,
        debt=payload.debt,
    )
    db.add(supplier)
    db.flush()

    add_event(
        db,
        "supplier",
        supplier.id,
        "created",
        note=f"Fournisseur {supplier.name} créé",
    )
    return supplier


@router.get("/suppliers/{supplier_id}/debt")
def get_supplier_debt(
    supplier_id: int,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("supplier.read")),
):
    """Retourne la dette totale d’un fournisseur précis."""
    supplier = suppliers_query(db).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    return {
        "supplier_id": supplier.id,
        "name": supplier.name,
        "debt": supplier.debt,
    }
