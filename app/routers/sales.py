from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.schemas.cancel_sale import CancelSalePayload
from app.schemas.sale import SaleCreate, SaleRead


router = APIRouter(tags=["ventes"])


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


@router.get("/sales", response_model=list[SaleRead])
def list_sales(db: Session = Depends(get_db)):
    """Liste toutes les ventes."""
    return db.query(Sale).all()


@router.post("/sales", response_model=SaleRead)
def create_sale(payload: SaleCreate, db: Session = Depends(get_db)):
    """Crée une vente multi-produits, diminue le stock et met à jour la dette client."""
    customer = db.query(Customer).filter(Customer.id == payload.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Client introuvable")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Au moins une ligne produit est requise")

    total_amount = 0
    resolved_items = []

    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La quantité doit être supérieure à zéro")

        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Produit introuvable : {item.product_id}")

        if product.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuffisant pour le produit {product.name}",
            )

        line_total = product.price * item.quantity
        total_amount += line_total
        resolved_items.append((product, item.quantity, product.price, line_total))

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

    sale = Sale(
        customer_id=payload.customer_id,
        total_amount=total_amount,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        status=status,
    )
    db.add(sale)
    db.flush()

    remaining_to_allocate = paid_amount
    created_sale_items: list[SaleItem] = []

    for product, quantity, unit_price, line_total in resolved_items:
        product.stock -= quantity

        allocated_amount = min(remaining_to_allocate, line_total)
        line_remaining = line_total - allocated_amount

        if line_remaining == 0:
            line_status = "paid"
        elif allocated_amount == 0:
            line_status = "credit"
        else:
            line_status = "partial"

        sale_item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit_price,
            line_total=line_total,
            paid_amount=allocated_amount,
            remaining_amount=line_remaining,
            status=line_status,
        )
        db.add(sale_item)
        db.flush()
        created_sale_items.append(sale_item)

        remaining_to_allocate -= allocated_amount

        add_stock_movement(
            db=db,
            product_id=product.id,
            movement_type="sale_out",
            quantity=-quantity,
            reference_type="sale",
            reference_id=sale.id,
            note=f"Vente au client {customer.name}",
        )

    if paid_amount > 0:
        payment = Payment(
            sale_id=sale.id,
            customer_id=customer.id,
            amount=paid_amount,
            channel=payload.payment_channel,
            reference=None,
        )
        db.add(payment)
        db.flush()

        for sale_item in created_sale_items:
            if sale_item.paid_amount > 0:
                db.add(
                    PaymentAllocation(
                        payment_id=payment.id,
                        sale_item_id=sale_item.id,
                        allocated_amount=sale_item.paid_amount,
                    )
                )

    customer.debt += remaining_amount

    add_event(
        db,
        "sale",
        sale.id,
        "created",
        amount_signed=total_amount,
        note="Vente créée",
    )

    db.commit()
    db.refresh(sale)
    return sale


@router.get("/sales/{sale_id}/items")
def get_sale_items(sale_id: int, db: Session = Depends(get_db)):
    """Affiche les lignes produit d’une vente."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Vente introuvable")

    return db.query(SaleItem).filter(SaleItem.sale_id == sale_id).all()


@router.get("/sales/{sale_id}/payments")
def get_sale_payments(sale_id: int, db: Session = Depends(get_db)):
    """Affiche les paiements liés à une vente."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Vente introuvable")

    return db.query(Payment).filter(Payment.sale_id == sale_id).all()


@router.post("/sales/{sale_id}/cancel", response_model=SaleRead)
def cancel_sale(sale_id: int, payload: CancelSalePayload, db: Session = Depends(get_db)):
    """Annule une vente sans la supprimer, remet le stock et corrige la dette."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Vente introuvable")

    if sale.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cette vente est déjà annulée")

    sale_items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
    if not sale_items:
        raise HTTPException(status_code=400, detail="Cette vente ne contient aucune ligne")

    customer = None
    if sale.customer_id:
        customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()

    for item in sale_items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product:
            product.stock += item.quantity
            add_stock_movement(
                db=db,
                product_id=product.id,
                movement_type="sale_cancel_reversal",
                quantity=item.quantity,
                reference_type="sale",
                reference_id=sale.id,
                note=payload.reason,
            )

    if customer:
        customer.debt = max(0, customer.debt - sale.remaining_amount)

    sale.status = "cancelled"
    sale.remaining_amount = 0

    add_event(
        db,
        "sale",
        sale.id,
        "cancelled",
        amount_signed=-sale.total_amount,
        note=payload.reason,
    )

    db.commit()
    db.refresh(sale)
    return sale
