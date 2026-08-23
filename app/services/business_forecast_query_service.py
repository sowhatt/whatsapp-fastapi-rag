import re

from sqlalchemy.orm import Session

from app.services.business_forecast_service import (
    build_month_forecast,
    render_month_forecast,
)


def detect_business_forecast_query(
    text: str,
) -> str | None:

    value = " ".join(text.lower().split())

    patterns = [
        r"prévision.*fin.*mois",
        r"prevision.*fin.*mois",
        r"forecast.*mois",
        r"combien.*vendre.*mois",
        r"combien.*vais.*vendre",
        r"quel.*ca.*fin.*mois",
        r"chiffre.*affaires.*fin.*mois",
        r"quelle.*marge.*fin.*mois",
        r"marge.*fin.*mois",
        r"projection.*mois",
        r"prévision.*chiffre.*affaires",
        r"prevision.*chiffre.*affaires",
    ]

    for pattern in patterns:
        if re.search(pattern, value):
            return "month_forecast"

    return None


def handle_business_forecast_query(
    *,
    query_type: str,
    merchant_id: int,
    db: Session,
) -> str:

    if query_type == "month_forecast":

        forecast = build_month_forecast(
            merchant_id=merchant_id,
            db=db,
        )

        return render_month_forecast(
            forecast
        )

    return (
        "ℹ️ Je n'ai pas compris "
        "la prévision demandée."
    )
