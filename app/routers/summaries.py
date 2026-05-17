from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry
from app.models.payment import Payment
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment

router = APIRouter(tags=["bilans"])


@router.get("/summary/activity")
def activity_summary(db: Session = Depends(get_db)):
    """Retourne une synthèse d’activité : ventes, achats, dettes clients et fournisseurs."""
    sales_total = (
        db.query(func.coalesce(func.sum(Sale.total_amount), 0))
        .filter(Sale.status != "cancelled")
        .scalar()
    )
    purchases_total = (
        db.query(func.coalesce(func.sum(Purchase.total_amount), 0))
        .filter(Purchase.status != "cancelled")
        .scalar()
    )
    customer_debt = db.query(func.coalesce(func.sum(Customer.debt), 0)).scalar()
    supplier_debt = db.query(func.coalesce(func.sum(Supplier.debt), 0)).scalar()

    return {
        "sales_total": sales_total,
        "purchases_total": purchases_total,
        "customer_debt": customer_debt,
        "supplier_debt": supplier_debt,
    }


@router.get("/summary/cashflow")
def cashflow_summary(db: Session = Depends(get_db)):
    """Retourne une synthèse de trésorerie liée et libre, sans mélanger les deux."""
    customer_payments = db.query(func.coalesce(func.sum(Payment.amount), 0)).scalar()
    supplier_payments = db.query(func.coalesce(func.sum(SupplierPayment.amount), 0)).scalar()

    manual_income = (
        db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(FinancialEntry.entry_type == "income", FinancialEntry.origin_kind == "manual")
        .scalar()
    )

    manual_expense = (
        db.query(func.coalesce(func.sum(FinancialEntry.amount), 0))
        .filter(FinancialEntry.entry_type == "expense", FinancialEntry.origin_kind == "manual")
        .scalar()
    )

    return {
        "linked_cashflow": {
            "customer_payments": customer_payments,
            "supplier_payments": supplier_payments,
        },
        "manual_cashflow": {
            "manual_income": manual_income,
            "manual_expense": manual_expense,
            "manual_net": manual_income - manual_expense,
        },
    }


@router.get("/summary/daily")
def daily_summary(db: Session = Depends(get_db)):
    """Retourne un bilan journalier structuré : activité, trésorerie liée, trésorerie libre et canaux."""
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
        "customer_payments": db.query(func.coalesce(func.sum(Payment.amount), 0)).scalar(),
        "supplier_payments": db.query(func.coalesce(func.sum(SupplierPayment.amount), 0)).scalar(),
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
