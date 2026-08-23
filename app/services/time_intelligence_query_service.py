import re

from sqlalchemy.orm import Session

from app.services.time_intelligence_service import (
    build_month_comparison,
    build_week_comparison,
    render_time_comparison,
)


def detect_time_intelligence_query(
    text: str,
) -> str | None:

    value = " ".join(
        text.lower().split()
    )

    month_patterns = [
        r"compare.*mois",
        r"mois.*mois dernier",
        r"par rapport au mois dernier",
        r"ventes.*mois dernier",
        r"chiffre d.affaires.*mois dernier",
        r"marge.*mois dernier",
        r"activité.*mois dernier",
        r"activite.*mois dernier",
    ]

    week_patterns = [
        r"compare.*semaine",
        r"semaine.*semaine dernière",
        r"semaine.*semaine derniere",
        r"par rapport à la semaine dernière",
        r"par rapport a la semaine derniere",
        r"ventes.*semaine dernière",
        r"ventes.*semaine derniere",
    ]

    for pattern in month_patterns:
        if re.search(pattern, value):
            return "month_comparison"

    for pattern in week_patterns:
        if re.search(pattern, value):
            return "week_comparison"

    return None


def handle_time_intelligence_query(
    *,
    query_type: str,
    merchant_id: int,
    db: Session,
    original_text: str | None = None,
) -> str:
    value = " ".join(
        (original_text or "").lower().split()
    )

    sales_only = bool(
        re.search(
            r"\b(ventes?|chiffre d.affaires|ca|marge)\b",
            value,
        )
    ) and not bool(
        re.search(
            r"\b(activité|activite|commerce|global|tout)\b",
            value,
        )
    )

    if query_type == "month_comparison":
        result = build_month_comparison(
            merchant_id=merchant_id,
            db=db,
        )

        return render_time_comparison(
            result,
            include_purchases=not sales_only,
        )

    if query_type == "week_comparison":
        result = build_week_comparison(
            merchant_id=merchant_id,
            db=db,
        )

        return render_time_comparison(
            result,
            include_purchases=not sales_only,
        )

    return (
        "ℹ️ Je n'ai pas compris la "
        "comparaison demandée."
    )
