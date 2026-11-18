from app.services.operation_currency import operation_currency
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.models.shop_operation import ShopOperation
from app.rbac import require_permission
from app.schemas.purchase import PurchaseCreate, PurchaseRead, CancelPurchasePayload
from app.services.shop_context_service import adjust_stock, get_current_shop_id, get_effective_stock, record_shop_operation

from app.services.purchase_idempotency import reserve_purchase, save_receipt
from app.services.purchase_transactions import lock_supplier, lock_purchase, lock_products, purchase_query

router = APIRouter(tags=["achats"])


def _purchases_query(db: Session):
    return purchase_query(db)


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


@router.post("/v2/purchases", response_model=PurchaseRead)
@router.post("/purchases", response_model=PurchaseRead)
def create_purchase(
    payload: PurchaseCreate,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("purchase.create")),
):
    """v2 requires a durable client key; legacy route fails closed without one."""
    try:
        request_id, receipt = reserve_purchase(db, payload)
        if receipt is not None:
            db.rollback()  # release the read transaction, never refresh the immutable receipt
            return receipt
        if payload.payment_effective_at and abs(datetime.now(timezone.utc)-payload.payment_effective_at)>timedelta(minutes=5):
            raise HTTPException(422,'Le paiement initial doit être déclaré maintenant')
        purchase = _create_purchase(payload, db)
        db.flush()
        db.refresh(purchase)
        receipt = save_receipt(db, request_id, purchase)
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise


def _create_purchase(payload: PurchaseCreate, db: Session):
    """Crée un achat multi-produits, augmente le stock et met à jour la dette fournisseur."""
    # A named supplier is still locked first. Anonymous purchases can only be
    # fully paid; nullable supplier columns already exist in the deployed schema.
    supplier = lock_supplier(db, payload.supplier_id) if payload.supplier_id is not None else None

    if not payload.items:
        raise HTTPException(status_code=400, detail="Au moins une ligne produit est requise")

    total_amount = 0
    resolved_items = []

    products = lock_products(db, [item.product_id for item in payload.items])
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La quantité doit être supérieure à zéro")

        if item.unit_cost < 0:
            raise HTTPException(status_code=400, detail="Le coût unitaire ne peut pas être négatif")

        product = products[item.product_id]
        if not product:
            raise HTTPException(status_code=404, detail=f"Produit introuvable : {item.product_id}")

        line_total = (
            item.line_total
            if item.line_total is not None
            else item.unit_cost * item.quantity
        )

        if line_total < 0:
            raise HTTPException(
                status_code=400,
                detail="Le montant de la ligne ne peut pas être négatif",
            )

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

    if remaining_amount > 0 and supplier is None:
        raise HTTPException(400, "Choisis un fournisseur pour le montant restant à payer")

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
        currency_code=operation_currency(db),        supplier_id=payload.supplier_id,
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

    supplier_payment = None
    if paid_amount > 0:
        supplier_payment = SupplierPayment(
            purchase_id=purchase.id,
            supplier_id=supplier.id if supplier else None,
            amount=paid_amount,
            channel=payload.payment_channel,
            reference=None,
            effective_at=payload.payment_effective_at or datetime.now(timezone.utc),
            effective_at_source='initial_declared_now' if payload.payment_effective_at else 'initial_server_now',
        )
        db.add(supplier_payment)
        db.flush()

    remaining_to_allocate = paid_amount

    for product, quantity, unit_cost, line_total in resolved_items:
        adjust_stock(product, quantity, db)

        allocated_amount = min(remaining_to_allocate, line_total)
        line_remaining = line_total - allocated_amount

        if line_remaining == 0:
            line_status = "paid"
        elif allocated_amount == 0:
            line_status = "credit"
        else:
            line_status = "partial"

        purchase_item = PurchaseItem(
            purchase_id=purchase.id,
            product_id=product.id,
            quantity=quantity,
            unit_cost=unit_cost,
            line_total=line_total,
            paid_amount=allocated_amount,
            remaining_amount=line_remaining,
            status=line_status,
        )
        db.add(purchase_item)
        db.flush()

        if supplier_payment is not None and allocated_amount > 0:
            db.add(
                SupplierPaymentAllocation(
                    supplier_payment_id=supplier_payment.id,
                    purchase_item_id=purchase_item.id,
                    allocated_amount=allocated_amount,
                )
            )

        remaining_to_allocate -= allocated_amount

        add_stock_movement(
            db=db,
            product_id=product.id,
            movement_type="purchase_in",
            quantity=quantity,
            reference_type="purchase",
            reference_id=purchase.id,
            note=f"Achat chez le fournisseur {supplier.name}" if supplier else "Achat comptant sans fournisseur",
        )

    if supplier:
        supplier.debt += remaining_amount

    add_event(
        db,
        "purchase",
        purchase.id,
        "created",
        amount_signed=total_amount,
        note="Achat créé",
    )

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

    payments=db.query(SupplierPayment).filter(SupplierPayment.purchase_id == purchase_id).order_by(SupplierPayment.id).all()
    allocations=db.query(SupplierPaymentAllocation).filter(SupplierPaymentAllocation.supplier_payment_id.in_([p.id for p in payments])).all() if payments else []
    return [{**{c.name:getattr(p,c.name) for c in SupplierPayment.__table__.columns},
             'currency_code':purchase.currency_code,
             'allocations':[{'purchase_item_id':a.purchase_item_id,'amount':a.allocated_amount} for a in allocations if a.supplier_payment_id==p.id]} for p in payments]


@router.post("/purchases/{purchase_id}/cancel", response_model=PurchaseRead)
def cancel_purchase(
    purchase_id: int,
    payload: CancelPurchasePayload,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("purchase.cancel")),
):
    try:
        purchase = _cancel_purchase(purchase_id, payload, db)
        db.flush()
        receipt = PurchaseRead.model_validate(purchase)
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise


def _cancel_purchase(purchase_id, payload, db):
    """Annule un achat sans le supprimer, corrige le stock et la dette fournisseur."""
    supplier, purchase = lock_purchase(db, purchase_id)

    if purchase.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cet achat est déjà annulé")

    purchase_items = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase.id).all()
    if not purchase_items:
        raise HTTPException(status_code=400, detail="Cet achat ne contient aucune ligne")

    products = lock_products(db, [item.product_id for item in purchase_items])

    for item in purchase_items:
        product = products[item.product_id]
        if not product:
            continue

        db.flush()
        if get_effective_stock(product, db, lock=True) < item.quantity:
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
        supplier.debt -= purchase.remaining_amount
        if supplier.debt < 0:
            raise HTTPException(409, "Dette fournisseur incohérente : rapprochement requis")

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

    return purchase
