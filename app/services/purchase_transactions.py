"""Shared locking order: supplier -> purchase -> items -> products -> inventory.

All mutations run in the caller's session, with one final commit. Refresh rows
under lock even when the session identity map contains a pre-validation read.
"""
from fastapi import HTTPException
from app.models.supplier import Supplier
from app.models.purchase import Purchase
from app.models.product import Product
from app.models.shop_operation import ShopOperation
from app.services.shop_context_service import get_current_shop_id


def lock_supplier(db, supplier_id):
    supplier = (db.query(Supplier).filter(Supplier.id == supplier_id)
                .populate_existing().with_for_update().first())
    if supplier is None:
        raise HTTPException(404, 'Fournisseur introuvable')
    return supplier


def purchase_query(db):
    query = db.query(Purchase)
    shop_id = get_current_shop_id(db)
    if shop_id is not None:
        query = query.filter(db.query(ShopOperation.id).filter(
            ShopOperation.entity_type == 'purchase',
            ShopOperation.entity_id == Purchase.id,
            ShopOperation.shop_id == shop_id,
            ShopOperation.merchant_id == Purchase.merchant_id,
        ).exists())
    return query


def lock_purchase(db, purchase_id):
    # Supplier id is immutable in all purchase writers. Read only the scalar;
    # never use an unlocked balance or a stale ORM object for validation.
    supplier_id = purchase_query(db).filter(Purchase.id == purchase_id).with_entities(Purchase.supplier_id).first()
    if supplier_id is None:
        raise HTTPException(404, 'Achat introuvable')
    supplier = lock_supplier(db, supplier_id[0]) if supplier_id[0] is not None else None
    purchase = (purchase_query(db).filter(Purchase.id == purchase_id)
                .populate_existing().with_for_update(of=Purchase).first())
    if purchase is None:
        raise HTTPException(404, 'Achat introuvable')
    return supplier, purchase


def lock_products(db, product_ids):
    products = (db.query(Product).filter(Product.id.in_(set(product_ids)))
                .order_by(Product.id).with_for_update().all())
    if get_current_shop_id(db) is None:
        for product in products:
            db.refresh(product)
    result = {product.id: product for product in products}
    if len(result) != len(set(product_ids)):
        raise HTTPException(404, 'Produit introuvable')
    return result


def validate_purchase_balances(db, purchase, items):
    """Reject inconsistent historical rows; never silently repair accounting."""
    from sqlalchemy import func
    from app.models.supplier_payment import SupplierPayment
    from app.models.supplier_payment_allocation import SupplierPaymentAllocation
    from app.models.purchase_item import PurchaseItem
    totals = (sum(i.line_total for i in items), sum(i.paid_amount for i in items),
              sum(i.remaining_amount for i in items))
    expected = (purchase.total_amount, purchase.paid_amount, purchase.remaining_amount)
    paid = db.query(func.coalesce(func.sum(SupplierPayment.amount), 0)).filter(
        SupplierPayment.purchase_id == purchase.id).scalar()
    allocated = (db.query(SupplierPayment.id, SupplierPayment.amount,
                         func.coalesce(func.sum(SupplierPaymentAllocation.allocated_amount), 0))
        .outerjoin(SupplierPaymentAllocation, SupplierPaymentAllocation.supplier_payment_id == SupplierPayment.id)
        .filter(SupplierPayment.purchase_id == purchase.id)
        .group_by(SupplierPayment.id, SupplierPayment.amount).all())
    wrong_target = (db.query(SupplierPaymentAllocation.id)
        .join(SupplierPayment, SupplierPayment.id == SupplierPaymentAllocation.supplier_payment_id)
        .join(PurchaseItem, PurchaseItem.id == SupplierPaymentAllocation.purchase_item_id)
        .filter(SupplierPayment.purchase_id == purchase.id, PurchaseItem.purchase_id != purchase.id).first())
    if (totals != expected or paid != purchase.paid_amount or wrong_target
            or any(amount != allocation for _, amount, allocation in allocated)
            or purchase.total_amount != purchase.paid_amount + purchase.remaining_amount
            or any(i.paid_amount < 0 or i.remaining_amount < 0 or i.line_total != i.paid_amount + i.remaining_amount for i in items)):
        raise HTTPException(409, "Soldes ou allocations incohérents : rapprochement requis")
