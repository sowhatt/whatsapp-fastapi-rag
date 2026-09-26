from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.models.shop_operation import ShopOperation
from app.rbac import require_permission
from app.schemas.purchase import PurchaseCreate, PurchaseRead, CancelPurchasePayload
from app.services.shop_context_service import adjust_stock, get_current_shop_id, get_effective_stock, record_shop_operation

router = APIRouter(tags=["achats"])


def _purchases_query(db: Session):
    query = db.query(Purchase)
    shop_id = get_current_shop_id(db)
    if shop_id is None:
        return query
    return query.join(
        ShopOperation,
        (ShopOperation.entity_type == "purchase")
        & (ShopOperation.entity_id == Purchase.id),
    ).filter(ShopOperation.shop_id == shop_id)


def _purchase_in_current_shop(db: Session, purchase_id: int):
    return _purchases_query(db).filter(Purchase.id == purchase_id).first()


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
def list_purchases(
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("purchase.read")),
):
    """Liste les achats de la boutique active, du plus récent au plus ancien."""
    return _purchases_query(db).order_by(Purchase.created_at.desc(), Purchase.id.desc()).all()


@router.post("/purchases", response_model=PurchaseRead)
def create_purchase(
    payload: PurchaseCreate,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("purchase.create")),
):
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

    if remaining_amount > 0 and payload.due_date is None:
        raise HTTPException(
            status_code=400,
            detail="Une date d'échéance est obligatoire pour une dette fournisseur",
        )

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
    record_shop_operation("purchase", purchase.id, db)

    for product, quantity, unit_cost, line_total in resolved_items:
        adjust_stock(product, quantity, db)

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
def get_purchase_items(
    purchase_id: int,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("purchase.read")),
):
    """Affiche les lignes produit d’un achat de la boutique active."""
    purchase = _purchase_in_current_shop(db, purchase_id)
    if not purchase:
        raise HTTPException(status_code=404, detail="Achat introuvable")

    return db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase_id).all()


@router.get("/purchases/{purchase_id}/payments")
def get_purchase_payments(
    purchase_id: int,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("purchase.read")),
):
    """Affiche les paiements liés à un achat de la boutique active."""
    purchase = _purchase_in_current_shop(db, purchase_id)
    if not purchase:
        raise HTTPException(status_code=404, detail="Achat introuvable")

    return db.query(SupplierPayment).filter(SupplierPayment.purchase_id == purchase_id).all()


@router.post("/purchases/{purchase_id}/cancel", response_model=PurchaseRead)
def cancel_purchase(
    purchase_id: int,
    payload: CancelPurchasePayload,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("purchase.cancel")),
):
    """Annule un achat sans le supprimer, corrige le stock et la dette fournisseur."""
    purchase = _purchase_in_current_shop(db, purchase_id)
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

        if get_effective_stock(product, db) < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible d’annuler l’achat : stock insuffisant pour le produit {product.name}",
            )

        adjust_stock(product, -item.quantity, db)

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
