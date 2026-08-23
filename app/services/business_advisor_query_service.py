import re

from sqlalchemy.orm import Session

from app.services.business_advisor_service import (
    build_business_advisor,
    render_business_advisor,
)


def detect_business_advisor_query(
    text: str,
) -> str | None:

    value = " ".join(
        text.lower().split()
    )

    patterns = [
        r"conseille.*commerce",
        r"conseil.*commerce",
        r"que dois.je faire",
        r"que me conseilles.tu",
        r"priorités.*commerce",
        r"priorites.*commerce",
        r"analyse.*et.*conseil",
        r"conseiller business",
        r"business advisor",
        r"comment améliorer.*commerce",
        r"comment ameliorer.*commerce",
    ]

    for pattern in patterns:
        if re.search(
            pattern,
            value,
            re.IGNORECASE,
        ):
            return "business_advisor"

    return None


def handle_business_advisor_query(
    *,
    query_type: str,
    merchant_id: int,
    db: Session,
) -> str:

    if query_type != "business_advisor":
        return (
            "ℹ️ Je n'ai pas compris "
            "le conseil demandé."
        )

    result = build_business_advisor(
        merchant_id=merchant_id,
        db=db,
    )

    return render_business_advisor(
        result
    )
