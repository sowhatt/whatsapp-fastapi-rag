"""Live purchasing aggregates, composable into one financial SQL snapshot."""
from datetime import datetime, time, timedelta
from sqlalchemy import func, select, case
from app.models.purchase import Purchase
from app.models.supplier_payment import SupplierPayment
from app.models.shop_operation import ShopOperation
from app.models.shop_inventory import ShopInventory
from app.models.product import Product


def in_period(query, column, since=None, until=None):
    # Business timestamps are stored as naive UTC, including historical imports.
    if since:
        query = query.where(column >= datetime.combine(since, time.min))
    if until:
        query = query.where(column < datetime.combine(until + timedelta(days=1), time.min))
    return query


def scoped_ids(model, kind, merchant_id, shop_id):
    return select(model.id).join(ShopOperation, (
        (ShopOperation.entity_type == kind) & (ShopOperation.entity_id == model.id)
    )).where(model.merchant_id == merchant_id, ShopOperation.merchant_id == merchant_id,
             ShopOperation.shop_id == shop_id)


def total(column, condition):
    return select(func.coalesce(func.sum(column), 0)).where(condition).scalar_subquery()


def purchasing_metric_columns(merchant_id, shop_id, since=None, until=None):
    all_purchases = scoped_ids(Purchase, 'purchase', merchant_id, shop_id)
    purchases = all_purchases.where(Purchase.status != 'cancelled')
    cohort = in_period(purchases, Purchase.created_at, since, until)
    payments = select(func.coalesce(func.sum(SupplierPayment.amount), 0)).where(
        SupplierPayment.merchant_id == merchant_id, SupplierPayment.purchase_id.in_(all_purchases))
    payments = in_period(payments, SupplierPayment.paid_at, since, until)
    known_credit = total(Purchase.total_amount - Purchase.initial_paid_amount, Purchase.id.in_(cohort))
    unknown_count = select(func.count()).select_from(Purchase).where(
        Purchase.id.in_(cohort), Purchase.initial_paid_amount.is_(None)).scalar_subquery()

    def stock_value(price):
        return select(func.coalesce(func.sum(ShopInventory.stock * func.coalesce(price, 0)), 0)).join(
            Product, Product.id == ShopInventory.product_id).where(
            ShopInventory.merchant_id == merchant_id, ShopInventory.shop_id == shop_id,
            Product.merchant_id == merchant_id).scalar_subquery()
    return [
        total(Purchase.total_amount, Purchase.id.in_(cohort)).label('purchases_total'),
        payments.scalar_subquery().label('purchases_paid'),
        # Never substitute the CURRENT paid amount for an unknown initial amount.
        case((unknown_count == 0, known_credit), else_=None).label('supplier_credit_generated'),
        known_credit.label('supplier_credit_known'),
        unknown_count.label('supplier_credit_unknown_count'),
        total(Purchase.remaining_amount, Purchase.id.in_(purchases)).label('supplier_payables'),
        stock_value(Product.purchase_price).label('stock_value'),
        stock_value(Product.price).label('potential_sales_value'),
    ]


def live_purchasing_metrics(db, merchant_id, shop_id, since=None, until=None):
    row = db.execute(select(*purchasing_metric_columns(merchant_id, shop_id, since, until))).mappings().one()
    return {key: int(value) if value is not None else None for key, value in row.items()}
