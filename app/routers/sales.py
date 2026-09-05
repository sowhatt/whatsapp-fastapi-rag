import time

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import get_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.shop_operation import ShopOperation
from app.rbac import require_permission
from app.schemas.cancel_sale import CancelSalePayload
from app.schemas.sale import SaleCreate, SaleRead
from app.services.shop_context_service import (
    adjust_stock,
    get_current_shop_id,
    get_effective_stock,
    record_shop_operation,
)


router = APIRouter(tags=["ventes"])


def _sales_query(db: Session):
    """Scope sales to the active shop when a shop context is selected."""
    query = db.query(Sale)
    shop_id = get_current_shop_id(db)
    if shop_id is None:
        return query
    return query.join(
        ShopOperation,
        (ShopOperation.entity_type == "sale")
        & (ShopOperation.entity_id == Sale.id),
    ).filter(ShopOperation.shop_id == shop_id)


def _sale_in_current_shop(db: Session, sale_id: int):
    return _sales_query(db).filter(Sale.id == sale_id).first()


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


def allocate_sale_number(
    db: Session,
    merchant_id: int | None,
) -> int | None:
    if merchant_id is None:
        return None

    (
        db.query(Merchant.id)
        .filter(Merchant.id == merchant_id)
        .with_for_update()
        .one()
    )

    current_max = (
        db.query(func.max(Sale.sale_number))
        .filter(Sale.merchant_id == merchant_id)
        .scalar()
    )

    return int(current_max or 0) + 1


@router.get("/sales", response_model=list[SaleRead])
def list_sales(
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.read")),
):
    return _sales_query(db).all()


@router.post("/sales", response_model=SaleRead)
def create_sale(
    payload: SaleCreate,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.create")),
):
    _sale_audit_started = time.monotonic()
    _sale_audit: dict[str, float | int | None] = {
        "merchant_id": get_current_merchant(db),
        "item_count": len(payload.items),
    }

    _stage_started = time.monotonic()
    cached_customer = db.info.get("_whatzabi_resolved_sale_customer")

    if cached_customer is not None and cached_customer.id == payload.customer_id:
        customer = cached_customer
        customer_source = "request_cache"
    else:
        customer = db.query(Customer).filter(Customer.id == payload.customer_id).first()
        customer_source = "database"

    _sale_audit["customer_source"] = customer_source
    _sale_audit["customer_lookup_s"] = round(time.monotonic() - _stage_started, 3)
    if not customer:
        raise HTTPException(status_code=404, detail="Client introuvable")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Au moins une ligne produit est requise")

    total_amount = 0
    resolved_items = []
    _stage_started = time.monotonic()

    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La quantité doit être supérieure à zéro")

        cached_products = db.info.get("_whatzabi_resolved_sale_products", {})
        product = cached_products.get(item.product_id)

        if product is None:
            product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Produit introuvable : {item.product_id}")

        available_stock = get_effective_stock(product, db)
        if available_stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuffisant pour le produit {product.name}",
            )

        unit_price = item.unit_price if item.unit_price is not None else product.price
        line_total = item.line_total if item.line_total is not None else unit_price * item.quantity
        total_amount += line_total
        resolved_items.append(
            (
                product,
                item.quantity,
                unit_price,
                line_total,
                int(product.purchase_price or 0),
            )
        )

    _sale_audit["product_resolution_s"] = round(time.monotonic() - _stage_started, 3)

    paid_amount = payload.paid_amount
    if paid_amount < 0:
        raise HTTPException(status_code=400, detail="Le montant payé ne peut pas être négatif")
    if paid_amount > total_amount:
        raise HTTPException(status_code=400, detail="Le montant payé ne peut pas dépasser le montant total")

    remaining_amount = total_amount - paid_amount
    if remaining_amount == 0:
        status = "paid"
    elif paid_amount == 0:
        status = "credit"
    else:
        status = "partial"

    merchant_id = get_current_merchant(db) or getattr(customer, "merchant_id", None)

    _stage_started = time.monotonic()
    sale_number = allocate_sale_number(db, merchant_id)
    _sale_audit["number_allocation_s"] = round(time.monotonic() - _stage_started, 3)

    sale = Sale(
        merchant_id=merchant_id,
        sale_number=sale_number,
        customer_id=payload.customer_id,
        total_amount=total_amount,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        status=status,
        due_date=payload.due_date,
    )
    _stage_started = time.monotonic()
    db.add(sale)
    db.flush()
    record_shop_operation("sale", sale.id, db)
    _sale_audit["sale_flush_s"] = round(time.monotonic() - _stage_started, 3)

    remaining_to_allocate = paid_amount
    created_sale_items: list[SaleItem] = []
    _stage_started = time.monotonic()

    for product, quantity, unit_price, line_total, unit_cost_snapshot in resolved_items:
        try:
            adjust_stock(product, -quantity, db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Stock insuffisant pour le produit {product.name}") from exc

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
            unit_cost_snapshot=unit_cost_snapshot,
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

    _sale_audit["items_stage_s"] = round(time.monotonic() - _stage_started, 3)
    _stage_started = time.monotonic()

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

    _sale_audit["payment_stage_s"] = round(time.monotonic() - _stage_started, 3)
    customer.debt += remaining_amount

    add_event(
        db,
        "sale",
        sale.id,
        "created",
        amount_signed=total_amount,
        note="Vente créée",
    )

    _stage_started = time.monotonic()
    previous_expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = previous_expire_on_commit

    _sale_audit["commit_s"] = round(time.monotonic() - _stage_started, 3)
    _sale_audit["refresh_s"] = 0.0
    _sale_audit["sale_id"] = sale.id
    _sale_audit["sale_number"] = sale.reference_number
    _sale_audit["total_s"] = round(time.monotonic() - _sale_audit_started, 3)

    print("SALE WRITE AUDIT:", _sale_audit)
    return sale


@router.get("/sales/{sale_id}/items")
def get_sale_items(
    sale_id: int,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.read")),
):
    sale = _sale_in_current_shop(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Vente introuvable")
    return db.query(SaleItem).filter(SaleItem.sale_id == sale_id).all()


@router.get("/sales/{sale_id}/payments")
def get_sale_payments(
    sale_id: int,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.read")),
):
    sale = _sale_in_current_shop(db, sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Vente introuvable")
    return db.query(Payment).filter(Payment.sale_id == sale_id).all()


@router.post("/sales/{sale_id}/cancel", response_model=SaleRead)
def cancel_sale(
    sale_id: int,
    payload: CancelSalePayload,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.cancel")),
):
    sale = _sale_in_current_shop(db, sale_id)
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
            adjust_stock(product, item.quantity, db)
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
