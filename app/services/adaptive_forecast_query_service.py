import re

from sqlalchemy.orm import Session

from app.services.adaptive_forecast_service import (
    build_adaptive_month_forecast,
    render_adaptive_forecast,
)


def detect_adaptive_forecast_query(
    text: str,
) -> str | None:

    value = " ".join(
        text.lower().split()
    )

    patterns = [
        r"prévision intelligente",
        r"prevision intelligente",
        r"forecast intelligent",
        r"prévision avancée",
        r"prevision avancee",
        r"forecast avancé",
        r"forecast avance",
        r"comment.*évolu(?:e|ent|er|eront).*commerce",
        r"comment.*evolu(?:e|ent|er|eront).*commerce",
        r"comment.*évolu(?:e|ent|er|eront).*ventes",
        r"comment.*evolu(?:e|ent|er|eront).*ventes",
        r"ventes.*accélèrent",
        r"ventes.*accelerent",
        r"activité.*accélère",
        r"activite.*accelere",
        r"activité.*ralentit",
        r"activite.*ralentit",
        r"tendance.*ventes",
        r"tendance.*chiffre.*affaires",
        r"projection intelligente",
    ]

    for pattern in patterns:
        if re.search(
            pattern,
            value,
            re.IGNORECASE,
        ):
            return "adaptive_month_forecast"

    return None


def handle_adaptive_forecast_query(
    *,
    query_type: str,
    merchant_id: int,
    db: Session,
) -> str:

    if query_type == "adaptive_month_forecast":

        result = build_adaptive_month_forecast(
            merchant_id=merchant_id,
            db=db,
        )

        return render_adaptive_forecast(
            result
        )

    return (
        "ℹ️ Je n'ai pas compris "
        "la prévision demandée."
    )
