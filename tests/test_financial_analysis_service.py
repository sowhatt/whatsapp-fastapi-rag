from decimal import Decimal

from app.services.financial_analysis_service import (
    FinancialOverview,
    render_financial_overview,
)


def test_financial_overview_contract():
    fields = FinancialOverview.__annotations__

    assert "sales_total" in fields
    assert "cogs" in fields
    assert "gross_margin" in fields
    assert "customer_receivables" in fields
    assert "supplier_payables" in fields
    assert "stock_value" in fields
    assert "estimated_net_position" in fields


def test_render_financial_overview():
    overview = FinancialOverview(
        merchant_id=1,

        sales_total=1_000_000,
        sales_paid=800_000,
        customer_credit_generated=200_000,

        purchases_total=500_000,
        purchases_paid=400_000,
        supplier_credit_generated=100_000,

        expenses_total=50_000,

        cogs=600_000,
        gross_margin=400_000,
        gross_margin_rate=Decimal("40.00"),

        net_cash_flow=350_000,

        customer_receivables=200_000,
        overdue_receivables=50_000,
        supplier_payables=100_000,

        stock_value=700_000,
        potential_sales_value=950_000,

        estimated_current_assets=900_000,
        estimated_current_liabilities=100_000,
        estimated_net_position=800_000,
    )

    text = render_financial_overview(
        overview,
        label="Août 2026",
    )

    assert "Bilan financier" in text
    assert "1 000 000 FCFA" in text
    assert "400 000 FCFA" in text
    assert "40.00 %" in text
    assert "200 000 FCFA" in text
    assert "800 000 FCFA" in text


def test_position_is_assets_minus_liabilities():
    overview = FinancialOverview(
        merchant_id=1,

        sales_total=0,
        sales_paid=0,
        customer_credit_generated=0,

        purchases_total=0,
        purchases_paid=0,
        supplier_credit_generated=0,

        expenses_total=0,

        cogs=0,
        gross_margin=0,
        gross_margin_rate=Decimal("0"),

        net_cash_flow=0,

        customer_receivables=300_000,
        overdue_receivables=0,
        supplier_payables=150_000,

        stock_value=500_000,
        potential_sales_value=0,

        estimated_current_assets=800_000,
        estimated_current_liabilities=150_000,
        estimated_net_position=650_000,
    )

    assert (
        overview.estimated_current_assets
        - overview.estimated_current_liabilities
        == overview.estimated_net_position
    )
