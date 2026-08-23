from types import SimpleNamespace

from app.services.adaptive_forecast_service import (
    _forecast_confidence,
)
from app.services.business_advisor_service import (
    BusinessAdvisorResult,
    render_business_advisor,
)
from app.services.inventory_queries_service import (
    handle_inventory_query,
)
from app.services.time_intelligence_query_service import (
    handle_time_intelligence_query,
)
from app.services.time_intelligence_service import (
    MetricComparison,
    TimeComparison,
    render_time_comparison,
)


def comparison():
    metric = MetricComparison(
        current=200,
        previous=100,
        difference=100,
        change_percent=100.0,
    )

    return TimeComparison(
        label="cette semaine",
        previous_label="même période de la semaine dernière",
        sales=metric,
        margin=metric,
        purchases=metric,
        expenses=metric,
        cash_flow=metric,
    )


def test_sales_comparison_hides_purchases(monkeypatch):
    monkeypatch.setattr(
        "app.services.time_intelligence_query_service."
        "build_week_comparison",
        lambda **kwargs: comparison(),
    )

    response = handle_time_intelligence_query(
        query_type="week_comparison",
        merchant_id=1,
        db=None,
        original_text=(
            "Compare mes ventes de cette semaine "
            "et la semaine dernière"
        ),
    )

    assert "Chiffre d'affaires" in response
    assert "Marge brute" in response
    assert "Achats" not in response


def test_activity_comparison_keeps_purchases():
    response = render_time_comparison(
        comparison(),
        include_purchases=True,
    )

    assert "Achats" in response


def test_slow_movers_are_limited_to_five(monkeypatch):
    items = [
        SimpleNamespace(
            status="slow",
            stock_value=10_000 - index,
            days_of_cover=100,
            product_name=f"Produit {index}",
        )
        for index in range(8)
    ]

    monkeypatch.setattr(
        "app.services.inventory_queries_service."
        "get_inventory_intelligence",
        lambda **kwargs: items,
    )

    response = handle_inventory_query(
        query_type="slow_movers",
        merchant_id=1,
        db=None,
    )

    assert response.count("• Produit") == 5
    assert "3 autre(s) produit(s)" in response


def test_extreme_volatility_forces_low_confidence():
    assert _forecast_confidence(
        history_days=60,
        revenue_volatility_pct=168.0,
        margin_volatility_pct=80.0,
    ) == "faible"


def test_advisor_explicitly_labels_periods():
    result = BusinessAdvisorResult(
        merchant_id=1,
        revenue=1_000_000,
        gross_margin=200_000,
        gross_margin_rate=20.0,
        forecast_revenue=1_500_000,
        forecast_margin=300_000,
        forecast_trajectory="stable",
        forecast_confidence="moyenne",
        stock_value=500_000,
        customer_debt=0,
        supplier_debt=0,
    )

    response = render_business_advisor(result)

    assert "historique enregistré" in response
    assert "fin du mois en cours" in response
