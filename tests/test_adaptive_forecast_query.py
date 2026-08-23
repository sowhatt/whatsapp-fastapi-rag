from app.services.adaptive_forecast_query_service import (
    detect_adaptive_forecast_query,
)


def test_detect_adaptive_forecast():
    cases = [
        "prévision intelligente",
        "forecast intelligent",
        "comment vont évoluer mes ventes ?",
        "est-ce que mes ventes accélèrent ?",
        "tendance de mon chiffre d'affaires",
    ]

    for text in cases:
        assert (
            detect_adaptive_forecast_query(text)
            == "adaptive_month_forecast"
        )


def test_normal_forecast_not_captured():
    assert (
        detect_adaptive_forecast_query(
            "prévision fin de mois"
        )
        is None
    )
