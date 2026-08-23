from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class DailyBusinessMetrics:
    merchant_id: int
    business_date: date
    sales_count: int
    sales_total: int
    sales_paid: int
    sales_credit: int
    purchases_count: int
    purchases_total: int
    purchases_paid: int
    purchases_credit: int
    expenses_total: int
    cogs: int
    gross_margin: int
    net_cash_flow: int


@dataclass
class ProductProfitability:
    merchant_id: int
    product_id: int
    product_name: str
    quantity_sold: int
    sales_revenue: int
    cogs: int
    gross_margin: int
    gross_margin_rate: Decimal
    current_stock: int
    current_stock_value: int


@dataclass
class CurrencyPurchaseExposure:
    merchant_id: int
    month: date
    original_currency: str
    purchase_count: int
    original_amount_total: int
    xof_amount_total: int
    average_exchange_rate: Decimal


def get_daily_metrics(
    *,
    merchant_id: int,
    db: Session,
    since: date | None = None,
    until: date | None = None,
) -> list[DailyBusinessMetrics]:
    sql = """
        SELECT *
        FROM mv_daily_business_metrics
        WHERE merchant_id = :merchant_id
    """

    params = {"merchant_id": merchant_id}

    if since is not None:
        sql += " AND business_date >= :since"
        params["since"] = since

    if until is not None:
        sql += " AND business_date <= :until"
        params["until"] = until

    sql += " ORDER BY business_date"

    rows = db.execute(
        text(sql),
        params,
    ).mappings().all()

    return [
        DailyBusinessMetrics(
            merchant_id=row["merchant_id"],
            business_date=row["business_date"],
            sales_count=int(row["sales_count"] or 0),
            sales_total=int(row["sales_total"] or 0),
            sales_paid=int(row["sales_paid"] or 0),
            sales_credit=int(row["sales_credit"] or 0),
            purchases_count=int(row["purchases_count"] or 0),
            purchases_total=int(row["purchases_total"] or 0),
            purchases_paid=int(row["purchases_paid"] or 0),
            purchases_credit=int(row["purchases_credit"] or 0),
            expenses_total=int(row["expenses_total"] or 0),
            cogs=int(row["cogs"] or 0),
            gross_margin=int(row["gross_margin"] or 0),
            net_cash_flow=int(row["net_cash_flow"] or 0),
        )
        for row in rows
    ]


def get_product_profitability(
    *,
    merchant_id: int,
    db: Session,
    limit: int = 10,
) -> list[ProductProfitability]:
    rows = db.execute(
        text("""
            SELECT *
            FROM mv_product_profitability
            WHERE merchant_id = :merchant_id
            ORDER BY gross_margin DESC, sales_revenue DESC
            LIMIT :limit
        """),
        {
            "merchant_id": merchant_id,
            "limit": limit,
        },
    ).mappings().all()

    return [
        ProductProfitability(
            merchant_id=row["merchant_id"],
            product_id=row["product_id"],
            product_name=row["product_name"],
            quantity_sold=int(row["quantity_sold"] or 0),
            sales_revenue=int(row["sales_revenue"] or 0),
            cogs=int(row["cogs"] or 0),
            gross_margin=int(row["gross_margin"] or 0),
            gross_margin_rate=Decimal(
                str(row["gross_margin_rate"] or 0)
            ),
            current_stock=int(row["current_stock"] or 0),
            current_stock_value=int(
                row["current_stock_value"] or 0
            ),
        )
        for row in rows
    ]


def get_currency_purchase_exposure(
    *,
    merchant_id: int,
    db: Session,
) -> list[CurrencyPurchaseExposure]:
    rows = db.execute(
        text("""
            SELECT *
            FROM mv_currency_purchase_exposure
            WHERE merchant_id = :merchant_id
            ORDER BY month DESC, original_currency
        """),
        {"merchant_id": merchant_id},
    ).mappings().all()

    return [
        CurrencyPurchaseExposure(
            merchant_id=row["merchant_id"],
            month=row["month"],
            original_currency=row["original_currency"],
            purchase_count=int(row["purchase_count"] or 0),
            original_amount_total=int(
                row["original_amount_total"] or 0
            ),
            xof_amount_total=int(
                row["xof_amount_total"] or 0
            ),
            average_exchange_rate=Decimal(
                str(row["average_exchange_rate"] or 0)
            ),
        )
        for row in rows
    ]


def refresh_analytics(db: Session) -> None:
    views = [
        "mv_daily_business_metrics",
        "mv_product_profitability",
        "mv_currency_purchase_exposure",
        "mv_customer_financial_position",
        "mv_supplier_financial_position",
        "mv_stock_analytics",
    ]

    for view in views:
        db.execute(
            text(
                f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"
            )
        )

    db.commit()
