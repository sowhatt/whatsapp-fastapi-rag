from pathlib import Path

from app.services.analytics_service import (
    CurrencyPurchaseExposure,
    DailyBusinessMetrics,
    ProductProfitability,
)


def test_analytics_sql_exists():
    path = Path(
        "app/analytics/sql/bi_01_materialized_views.sql"
    )

    assert path.exists()


def test_sql_contains_required_materialized_views():
    sql = Path(
        "app/analytics/sql/bi_01_materialized_views.sql"
    ).read_text()

    assert "mv_daily_business_metrics" in sql
    assert "mv_product_profitability" in sql
    assert "mv_currency_purchase_exposure" in sql


def test_daily_metrics_contract():
    assert "gross_margin" in DailyBusinessMetrics.__annotations__
    assert "net_cash_flow" in DailyBusinessMetrics.__annotations__


def test_product_profitability_contract():
    assert "gross_margin" in ProductProfitability.__annotations__
    assert "gross_margin_rate" in ProductProfitability.__annotations__


def test_currency_exposure_contract():
    assert (
        "average_exchange_rate"
        in CurrencyPurchaseExposure.__annotations__
    )
