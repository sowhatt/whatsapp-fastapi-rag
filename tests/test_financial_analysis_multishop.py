from decimal import Decimal
from unittest.mock import MagicMock

from app.services.financial_analysis_service import (
    get_financial_overview,
)


class MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


def test_financial_overview_uses_shop_views_when_shop_selected():
    db = MagicMock()

    db.execute.side_effect = [
        MappingResult({
            "sales_total": 51000,
            "sales_paid": 49000,
            "customer_credit_generated": 2000,
            "purchases_total": 40000,
            "purchases_paid": 0,
            "supplier_credit_generated": 40000,
            "expenses_total": 0,
            "cogs": 30000,
            "gross_margin": 21000,
            "net_cash_flow": 9000,
        }),
        MappingResult({
            "receivables": 2000,
            "overdue": 0,
        }),
        MappingResult({
            "payables": 40000,
        }),
        MappingResult({
            "stock_value": 100000,
            "potential_sales_value": 150000,
        }),
    ]

    result = get_financial_overview(
        merchant_id=1,
        shop_id=2,
        db=db,
    )

    assert result.sales_total == 51000
    assert result.customer_receivables == 2000
    assert result.supplier_payables == 40000
    assert result.gross_margin == 21000
    assert result.gross_margin_rate == Decimal("41.18")

    sql = [
        str(call.args[0])
        for call in db.execute.call_args_list
    ]

    assert "mv_daily_business_metrics_by_shop" in sql[0]
    assert "mv_customer_financial_position_by_shop" in sql[1]
    assert "mv_supplier_financial_position_by_shop" in sql[2]
    assert "mv_stock_analytics_by_shop" in sql[3]

    for call in db.execute.call_args_list:
        assert call.args[1]["merchant_id"] == 1
        assert call.args[1]["shop_id"] == 2


def test_financial_overview_keeps_merchant_views_without_shop():
    db = MagicMock()

    db.execute.side_effect = [
        MappingResult({
            "sales_total": 51000,
            "sales_paid": 49000,
            "customer_credit_generated": 2000,
            "purchases_total": 40000,
            "purchases_paid": 0,
            "supplier_credit_generated": 40000,
            "expenses_total": 0,
            "cogs": 30000,
            "gross_margin": 21000,
            "net_cash_flow": 9000,
        }),
        MappingResult({
            "receivables": 2000,
            "overdue": 0,
        }),
        MappingResult({
            "payables": 40000,
        }),
        MappingResult({
            "stock_value": 100000,
            "potential_sales_value": 150000,
        }),
    ]

    get_financial_overview(
        merchant_id=1,
        db=db,
    )

    sql = [
        str(call.args[0])
        for call in db.execute.call_args_list
    ]

    assert "FROM mv_daily_business_metrics\n" in sql[0]
    assert "FROM mv_customer_financial_position\n" in sql[1]
    assert "FROM mv_supplier_financial_position\n" in sql[2]
    assert "FROM mv_stock_analytics\n" in sql[3]

    for call in db.execute.call_args_list:
        assert "shop_id" not in call.args[1]
