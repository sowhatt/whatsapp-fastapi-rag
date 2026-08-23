from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.schemas.purchase import PurchaseCreate, PurchaseRead, CancelPurchasePayload

router = APIRouter(tags=["achats"])


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


def add_stock_movement(
    db: Session,
    product_id: int,
    movement_type: str,
    quantity: int,
    reference_type: str,
    reference_id: int,
    note: str | None = None,
):
    from app.models.stock_movement import StockMovement

    db.add(
        StockMovement(
            product_id=product_id,
            movement_type=movement_type,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
        )
    )


@router.get("/purchases", response_model=list[PurchaseRead])
def list_purchases(db: Session = Depends(get_db)):
    """Liste tous les achats fournisseurs."""
    return db.query(Purchase).all()


@router.post("/purchases", response_model=PurchaseRead)
def create_purchase(payload: PurchaseCreate, db: Session = Depends(get_db)):
    """Crée un achat multi-produits, augmente le stock et met à jour la dette fournisseur."""
    supplier = db.query(Supplier).filter(Supplier.id == payload.supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Au moins une ligne produit est requise")

    total_amount = 0
    resolved_items = []

    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La quantité doit être supérieure à zéro")

        if item.unit_cost < 0:
            raise HTTPException(status_code=400, detail="Le coût unitaire ne peut pas être négatif")

        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Produit introuvable : {item.product_id}")

        line_total = item.unit_cost * item.quantity
        total_amount += line_total
        resolved_items.append((product, item.quantity, item.unit_cost, line_total))

    paid_amount = payload.paid_amount
    if paid_amount < 0:
        raise HTTPException(status_code=400, detail="Le montant payé ne peut pas être négatif")

    if paid_amount > total_amount:
        raise HTTPException(
            status_code=400,
            detail="Le montant payé ne peut pas dépasser le montant total",
        )

    remaining_amount = total_amount - paid_amount

    if remaining_amount == 0:
        status = "paid"
    elif paid_amount == 0:
        status = "credit"
    else:
        status = "partial"

    purchase = Purchase(
        supplier_id=payload.supplier_id,
        total_amount=total_amount,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        status=status,
        due_date=payload.due_date,
        original_amount=(
            payload.original_amount
            if payload.original_amount is not None
            else total_amount
        ),
        original_currency=(
            payload.original_currency or "XOF"
        ).upper(),
        exchange_rate=payload.exchange_rate,
    )
    db.add(purchase)
    db.flush()

    for product, quantity, unit_cost, line_total in resolved_items:
        product.stock += quantity

        db.add(
            PurchaseItem(
                purchase_id=purchase.id,
                product_id=product.id,
                quantity=quantity,
                unit_cost=unit_cost,
                line_total=line_total,
                paid_amount=0,
                remaining_amount=line_total,
                status="credit",
            )
        )

        add_stock_movement(
            db=db,
            product_id=product.id,
            movement_type="purchase_in",
            quantity=quantity,
            reference_type="purchase",
            reference_id=purchase.id,
            note=f"Achat chez le fournisseur {supplier.name}",
        )

    if paid_amount > 0:
        db.add(
            SupplierPayment(
                purchase_id=purchase.id,
                supplier_id=supplier.id,
                amount=paid_amount,
                channel=payload.payment_channel,
                reference=None,
            )
        )

    supplier.debt += remaining_amount

    add_event(
        db,
        "purchase",
        purchase.id,
        "created",
        amount_signed=total_amount,
        note="Achat créé",
    )

    db.commit()
    db.refresh(purchase)
    return purchase


@router.get("/purchases/{purchase_id}/items")
def get_purchase_items(purchase_id: int, db: Session = Depends(get_db)):
    """Affiche les lignes produit d’un achat."""
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Achat introuvable")

    return db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase_id).all()


@router.get("/purchases/{purchase_id}/payments")
def get_purchase_payments(purchase_id: int, db: Session = Depends(get_db)):
    """Affiche les paiements liés à un achat."""
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Achat introuvable")

    return db.query(SupplierPayment).filter(SupplierPayment.purchase_id == purchase_id).all()


@router.post("/purchases/{purchase_id}/cancel", response_model=PurchaseRead)
def cancel_purchase(purchase_id: int, payload: CancelPurchasePayload, db: Session = Depends(get_db)):
    """Annule un achat sans le supprimer, corrige le stock et la dette fournisseur."""
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Achat introuvable")

    if purchase.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cet achat est déjà annulé")

    purchase_items = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase.id).all()
    if not purchase_items:
        raise HTTPException(status_code=400, detail="Cet achat ne contient aucune ligne")

    supplier = None
    if purchase.supplier_id:
        supplier = db.query(Supplier).filter(Supplier.id == purchase.supplier_id).first()

    for item in purchase_items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            continue

        if product.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible d’annuler l’achat : stock insuffisant pour le produit {product.name}",
            )

        product.stock -= item.quantity

        add_stock_movement(
            db=db,
            product_id=product.id,
            movement_type="purchase_cancel_reversal",
            quantity=-item.quantity,
            reference_type="purchase",
            reference_id=purchase.id,
            note=payload.reason,
        )

    if supplier:
        supplier.debt = max(0, supplier.debt - purchase.remaining_amount)

    purchase.status = "cancelled"
    purchase.remaining_amount = 0
    purchase.cancelled_at = datetime.utcnow()
    purchase.cancellation_reason = payload.reason

    add_event(
        db,
        "purchase",
        purchase.id,
        "cancelled",
        amount_signed=-purchase.total_amount,
        note=payload.reason,
    )

    db.commit()
    db.refresh(purchase)
    return purchase
