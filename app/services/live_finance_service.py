"""Active-shop cockpit: one SELECT / one PostgreSQL snapshot, no BI refresh.

Activity follows operation dates; cash follows payment dates, including payments
for later-cancelled operations (cancellation is not a refund). Positions are current
and deliberately independent of the selected activity period.
"""
from sqlalchemy import select, func
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.payment import Payment
from app.models.financial_entry import FinancialEntry
from app.services.purchasing_finance_service import (
    purchasing_metric_columns, scoped_ids, in_period, total,
)


def live_financial_metrics(db, merchant_id, shop_id, since=None, until=None):
    all_sales = scoped_ids(Sale, 'sale', merchant_id, shop_id)
    sales = all_sales.where(Sale.status != 'cancelled')
    cohort = in_period(sales, Sale.created_at, since, until)
    payments = in_period(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.merchant_id == merchant_id, Payment.sale_id.in_(all_sales)),
        Payment.paid_at, since, until)
    expenses = in_period(scoped_ids(FinancialEntry, 'financial_entry', merchant_id, shop_id),
                         FinancialEntry.created_at, since, until)
    columns = purchasing_metric_columns(merchant_id, shop_id, since, until) + [
        total(Sale.total_amount, Sale.id.in_(cohort)).label('sales_total'),
        payments.scalar_subquery().label('sales_paid'),
        # Legacy API name: this is the current outstanding amount of the cohort.
        total(Sale.remaining_amount, Sale.id.in_(cohort)).label('customer_credit_generated'),
        total(SaleItem.quantity * func.coalesce(SaleItem.unit_cost_snapshot, 0),
              SaleItem.sale_id.in_(cohort)).label('cogs'),
        total(FinancialEntry.amount, FinancialEntry.id.in_(expenses.where(
            FinancialEntry.entry_type == 'expense'))).label('expenses_total'),
        total(Sale.remaining_amount, Sale.id.in_(sales)).label('receivables'),
        total(Sale.remaining_amount, Sale.id.in_(sales.where(
            Sale.remaining_amount > 0, Sale.due_date < func.current_date()))).label('overdue'),
    ]
    row = dict(db.execute(select(*columns)).mappings().one())
    row['gross_margin'] = row['sales_total'] - row['cogs']
    row['net_cash_flow'] = row['sales_paid'] - row['purchases_paid'] - row['expenses_total']
    return row
