import os
import re
from dataclasses import dataclass
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.adaptive_forecast_query_service import (
    detect_adaptive_forecast_query,
    handle_adaptive_forecast_query,
)
from app.services.analytics_service import refresh_analytics
from app.services.business_advisor_query_service import (
    detect_business_advisor_query,
    handle_business_advisor_query,
)
from app.services.business_forecast_query_service import (
    detect_business_forecast_query,
    handle_business_forecast_query,
)
from app.services.financial_queries_service import (
    detect_financial_query,
    handle_financial_query,
)
from app.services.inventory_queries_service import (
    detect_inventory_query,
    handle_inventory_query,
)
from app.services.time_intelligence_query_service import (
    detect_time_intelligence_query,
    handle_time_intelligence_query,
)


ReadOnlyIntent = Literal[
    "product_profitability",
    "product_losses",
    "customer_receivables",
    "stock_concentration",
    "nigeria_purchases",
    "inventory_overview",
    "slow_movers",
    "stockout_risk",
    "replenishment_candidates",
    "month_forecast",
    "adaptive_month_forecast",
    "week_comparison",
    "month_comparison",
    "business_advisor",
    "unknown",
]


class SemanticReadOnlyIntent(BaseModel):
    intent: ReadOnlyIntent
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )


@dataclass(frozen=True)
class ReadOnlyQueryRoute:
    family: str
    query_type: str
    source: str
    confidence: float


FAMILY_BY_INTENT = {
    "product_profitability": "financial",
    "product_losses": "financial",
    "customer_receivables": "financial",
    "stock_concentration": "financial",
    "nigeria_purchases": "financial",
    "inventory_overview": "inventory",
    "slow_movers": "inventory",
    "stockout_risk": "inventory",
    "replenishment_candidates": "inventory",
    "month_forecast": "forecast",
    "adaptive_month_forecast": "adaptive_forecast",
    "week_comparison": "time",
    "month_comparison": "time",
    "business_advisor": "advisor",
}


SYSTEM_PROMPT = """
Tu es le routeur sémantique BI de Whatzabi, un assistant de gestion
voice-first pour commerçants francophones.

Tu classes uniquement les QUESTIONS ANALYTIQUES EN LECTURE SEULE.

Intentions autorisées :
- product_profitability
- product_losses
- customer_receivables
- stock_concentration
- nigeria_purchases
- inventory_overview
- slow_movers
- stockout_risk
- replenishment_candidates
- month_forecast
- adaptive_month_forecast
- week_comparison
- month_comparison
- business_advisor
- unknown

Règles :
1. Une vente, un achat, un paiement, une dépense, une annulation ou
   une modification doit toujours être classé unknown.
2. N'extrais aucun montant, client, produit ou fournisseur.
3. Tolère les fautes, accents locaux et erreurs de transcription.
4. « Où est bloqué mon agent ? » signifie probablement
   stock_concentration lorsque « agent » est une transcription
   phonétique de « argent ».
5. Les formes singulier/pluriel sont équivalentes :
   « quel produit risque » et « quels produits risquent ».
6. « Compare mes ventes de cette semaine et la semaine dernière »
   signifie week_comparison.
7. En cas de doute, retourne unknown avec une faible confiance.
"""


_STRONG_ANALYTICS_MARKERS = re.compile(
    r"\b("
    r"analyse|analytique|rentab|marge|créance|creance|"
    r"débiteur|debiteur|immobilis|bloqu|capital|trésorerie|"
    r"tresorerie|prévision|prevision|forecast|projection|"
    r"tendance|évolu|evolu|compare|comparaison|"
    r"semaine dernière|semaine derniere|mois dernier|"
    r"rotation|dorment|dormant|rupture|épuis|epuis|"
    r"réappro|reappro|conseille|conseil|amélior|amelior|"
    r"nigeria|nigéria|naira|ngn"
    r")",
    re.IGNORECASE,
)


def _looks_like_analytics_question(text: str) -> bool:
    value = " ".join(text.lower().split())

    return bool(
        _STRONG_ANALYTICS_MARKERS.search(value)
    )


def _deterministic_route(
    text: str,
) -> ReadOnlyQueryRoute | None:
    detectors = [
        (
            "advisor",
            detect_business_advisor_query,
        ),
        (
            "adaptive_forecast",
            detect_adaptive_forecast_query,
        ),
        (
            "forecast",
            detect_business_forecast_query,
        ),
        (
            "time",
            detect_time_intelligence_query,
        ),
        (
            "inventory",
            detect_inventory_query,
        ),
        (
            "financial",
            detect_financial_query,
        ),
    ]

    for family, detector in detectors:
        query_type = detector(text)

        if query_type:
            return ReadOnlyQueryRoute(
                family=family,
                query_type=query_type,
                source="deterministic",
                confidence=1.0,
            )

    return None


def classify_semantic_read_only_query(
    text: str,
) -> ReadOnlyQueryRoute | None:
    if not _looks_like_analytics_question(text):
        return None

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return None

    model = os.getenv(
        "OPENAI_BI_ROUTER_MODEL",
        os.getenv(
            "OPENAI_INTENT_MODEL",
            "gpt-4.1-mini",
        ),
    )

    minimum_confidence = float(
        os.getenv(
            "OPENAI_BI_ROUTER_MIN_CONFIDENCE",
            "0.80",
        )
    )

    try:
        client = OpenAI(
            api_key=api_key,
            timeout=8.0,
            max_retries=0,
        )

        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            text_format=SemanticReadOnlyIntent,
        )

        parsed = response.output_parsed

    except Exception as exc:
        print(
            "SEMANTIC BI ROUTER ERROR:",
            type(exc).__name__,
            str(exc),
        )
        return None

    if parsed is None:
        return None

    if parsed.intent == "unknown":
        return None

    if parsed.confidence < minimum_confidence:
        return None

    family = FAMILY_BY_INTENT.get(
        parsed.intent
    )

    if family is None:
        return None

    return ReadOnlyQueryRoute(
        family=family,
        query_type=parsed.intent,
        source="semantic",
        confidence=float(parsed.confidence),
    )


def detect_read_only_query(
    text: str,
) -> ReadOnlyQueryRoute | None:
    deterministic = _deterministic_route(text)

    if deterministic is not None:
        return deterministic

    return classify_semantic_read_only_query(text)


def handle_read_only_query(
    *,
    route: ReadOnlyQueryRoute,
    merchant_id: int,
    db: Session,
) -> str:
    refresh_analytics(db)

    if route.family == "financial":
        return handle_financial_query(
            query_type=route.query_type,
            merchant_id=merchant_id,
            db=db,
        )

    if route.family == "inventory":
        return handle_inventory_query(
            query_type=route.query_type,
            merchant_id=merchant_id,
            db=db,
        )

    if route.family == "forecast":
        return handle_business_forecast_query(
            query_type=route.query_type,
            merchant_id=merchant_id,
            db=db,
        )

    if route.family == "adaptive_forecast":
        return handle_adaptive_forecast_query(
            query_type=route.query_type,
            merchant_id=merchant_id,
            db=db,
        )

    if route.family == "time":
        return handle_time_intelligence_query(
            query_type=route.query_type,
            merchant_id=merchant_id,
            db=db,
        )

    if route.family == "advisor":
        return handle_business_advisor_query(
            query_type=route.query_type,
            merchant_id=merchant_id,
            db=db,
        )

    raise ValueError(
        f"Famille BI inconnue : {route.family}"
    )
