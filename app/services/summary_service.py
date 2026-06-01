from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sale import Sale
from app.models.purchase import Purchase
from app.models.customer import Customer
from app.models.supplier import Supplier
from app.models.financial_entry import FinancialEntry


def get_daily_summary_data(db: Session):
    activity = {
        "sales_total": db.query(func.coalesce(func.sum(Sale.total_amount), 0))
        .filter(Sale.status != "cancelled")
        .scalar(),
        "purchases_total": db.query(func.coalesce(func.sum(Purchase.total_amount), 0))
        .filter(Purchase.status != "cancelled")
        .scalar(),
        "customer_debt": db.query(func.coalesce(func.sum(Customer.debt), 0)).scalar(),
        "supplier_debt": db.query(func.coalesce(func.sum(Supplier.debt), 0)).scalar(),
    }

    linked_cashflow = {
        "customer_payments": 0,
        "supplier_payments": 0,
    }

    manual_cashflow = {
        "manual_income": db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(FinancialEntry.entry_type == "income", FinancialEntry.origin_kind == "manual")
        .scalar(),
        "manual_expense": db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(FinancialEntry.entry_type == "expense", FinancialEntry.origin_kind == "manual")
        .scalar(),
    }

    manual_cashflow["manual_net"] = manual_cashflow["manual_income"] - manual_cashflow["manual_expense"]

    by_channel = {
        "cash_income": db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(
            FinancialEntry.entry_type == "income",
            FinancialEntry.channel == "cash",
            FinancialEntry.origin_kind == "manual",
        )
        .scalar(),
        "moov_income": db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(
            FinancialEntry.entry_type == "income",
            FinancialEntry.channel == "moov_money",
            FinancialEntry.origin_kind == "manual",
        )
        .scalar(),
        "mtn_income": db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(
            FinancialEntry.entry_type == "income",
            FinancialEntry.channel == "mtn_momo",
            FinancialEntry.origin_kind == "manual",
        )
        .scalar(),
    }

    return {
        "activity": activity,
        "linked_cashflow": linked_cashflow,
        "manual_cashflow": manual_cashflow,
        "by_channel": by_channel,
    }