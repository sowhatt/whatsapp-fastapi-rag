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
    "fast_movers",
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
    reason: str = Field(
        default="",
        max_length=160,
    )


@dataclass(frozen=True)
class ReadOnlyQueryRoute:
    family: str
    query_type: str
    source: str
    confidence: float


@dataclass(frozen=True)
class SemanticRoutingDecision:
    route: ReadOnlyQueryRoute | None
    intent: str
    confidence: float
    threshold: float
    reason: str


FAMILY_BY_INTENT = {
    "product_profitability": "financial",
    "product_losses": "financial",
    "customer_receivables": "financial",
    "stock_concentration": "financial",
    "nigeria_purchases": "financial",
    "inventory_overview": "inventory",
    "slow_movers": "inventory",
    "fast_movers": "inventory",
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
- fast_movers
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
7. Pour une question de forme « quels produits [mot mal transcrit]
   dans mon stock », interprète le sens global et non le mot littéral.
   Des mots incohérents comme « dorme », « d'horne », « d'armes » ou
   « d'homme » peuvent être des transcriptions de « dorment » :
   classe alors slow_movers.
8. « Quels produits ai-je dans mon stock ? » signifie
   inventory_overview, car aucune rotation lente n'est demandée.
9. Si les produits se vendent rapidement, classe fast_movers.
10. En cas de doute réel, retourne unknown avec une faible confiance.
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


_AMBIGUOUS_INVENTORY_QUESTION = re.compile(
    r"\b(quel(?:s|le|les)?|quoi|qu.?est.?ce)\b"
    r".*\b(produits?|articles?)\b"
    r".*\b(stock|rayons?)\b",
    re.IGNORECASE,
)

_EXPLICIT_WRITE_MARKERS = re.compile(
    r"\b(ajoute|ajouter|supprime|supprimer|"
    r"modifie|modifier|crée|cree|créer|creer|"
    r"enregistre|enregistrer)\b",
    re.IGNORECASE,
)


def _looks_like_analytics_question(text: str) -> bool:
    value = " ".join(text.lower().split())

    if _EXPLICIT_WRITE_MARKERS.search(value):
        return False

    return bool(
        _STRONG_ANALYTICS_MARKERS.search(value)
        or _AMBIGUOUS_INVENTORY_QUESTION.search(value)
    )


def _is_ambiguous_inventory_question(
    text: str,
) -> bool:
    value = " ".join(text.lower().split())

    return bool(
        _AMBIGUOUS_INVENTORY_QUESTION.search(value)
    )


def _inventory_clarification_route(
    confidence: float = 0.0,
) -> ReadOnlyQueryRoute:
    return ReadOnlyQueryRoute(
        family="inventory",
        query_type="inventory_clarification",
        source="semantic_clarification",
        confidence=confidence,
    )


def _resolve_semantic_decision(
    *,
    text: str,
    parsed: SemanticReadOnlyIntent | None,
    default_threshold: float = 0.80,
    ambiguous_inventory_threshold: float = 0.65,
) -> SemanticRoutingDecision:
    ambiguous_inventory = (
        _is_ambiguous_inventory_question(text)
    )

    threshold = (
        ambiguous_inventory_threshold
        if ambiguous_inventory
        else default_threshold
    )

    if parsed is None:
        route = (
            _inventory_clarification_route()
            if ambiguous_inventory
            else None
        )

        return SemanticRoutingDecision(
            route=route,
            intent="none",
            confidence=0.0,
            threshold=threshold,
            reason="no_semantic_result",
        )

    confidence = float(parsed.confidence)

    if parsed.intent == "unknown":
        route = (
            _inventory_clarification_route(
                confidence
            )
            if ambiguous_inventory
            else None
        )

        return SemanticRoutingDecision(
            route=route,
            intent=parsed.intent,
            confidence=confidence,
            threshold=threshold,
            reason="unknown_intent",
        )

    family = FAMILY_BY_INTENT.get(
        parsed.intent
    )

    if (
        ambiguous_inventory
        and family != "inventory"
    ):
        return SemanticRoutingDecision(
            route=_inventory_clarification_route(
                confidence
            ),
            intent=parsed.intent,
            confidence=confidence,
            threshold=threshold,
            reason="non_inventory_intent_rejected",
        )

    if confidence < threshold:
        route = (
            _inventory_clarification_route(
                confidence
            )
            if ambiguous_inventory
            else None
        )

        return SemanticRoutingDecision(
            route=route,
            intent=parsed.intent,
            confidence=confidence,
            threshold=threshold,
            reason="confidence_below_threshold",
        )

    if family is None:
        return SemanticRoutingDecision(
            route=None,
            intent=parsed.intent,
            confidence=confidence,
            threshold=threshold,
            reason="unknown_family",
        )

    return SemanticRoutingDecision(
        route=ReadOnlyQueryRoute(
            family=family,
            query_type=parsed.intent,
            source="semantic",
            confidence=confidence,
        ),
        intent=parsed.intent,
        confidence=confidence,
        threshold=threshold,
        reason="accepted",
    )


def _log_semantic_decision(
    decision: SemanticRoutingDecision,
) -> None:
    print(
        "SEMANTIC BI ROUTER DECISION:",
        {
            "intent": decision.intent,
            "confidence": decision.confidence,
            "threshold": decision.threshold,
            "reason": decision.reason,
            "route": (
                decision.route.query_type
                if decision.route
                else None
            ),
        },
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

    ambiguous_inventory = (
        _is_ambiguous_inventory_question(text)
    )

    api_key = os.getenv("OPENAI_API_KEY")

    default_threshold = float(
        os.getenv(
            "OPENAI_BI_ROUTER_MIN_CONFIDENCE",
            "0.80",
        )
    )

    ambiguous_threshold = float(
        os.getenv(
            "OPENAI_BI_AMBIGUOUS_MIN_CONFIDENCE",
            "0.65",
        )
    )

    if not api_key:
        decision = _resolve_semantic_decision(
            text=text,
            parsed=None,
            default_threshold=default_threshold,
            ambiguous_inventory_threshold=(
                ambiguous_threshold
            ),
        )

        decision = SemanticRoutingDecision(
            route=decision.route,
            intent=decision.intent,
            confidence=decision.confidence,
            threshold=decision.threshold,
            reason="missing_api_key",
        )

        _log_semantic_decision(decision)
        return decision.route

    model = os.getenv(
        "OPENAI_BI_ROUTER_MODEL",
        os.getenv(
            "OPENAI_INTENT_MODEL",
            "gpt-4.1-mini",
        ),
    )

    semantic_input = text

    if ambiguous_inventory:
        semantic_input = (
            "Transcription vocale potentiellement imparfaite. "
            "Déduis l'intention métier globale. "
            "Une expression incohérente entre « produits » et "
            "« stock » peut être une mauvaise transcription de "
            "« produits qui dorment dans mon stock ». "
            "Transcription : "
            f"{text}"
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
                    "content": semantic_input,
                },
            ],
            text_format=SemanticReadOnlyIntent,
        )

        parsed = response.output_parsed

    except Exception as exc:
        print(
            "SEMANTIC BI ROUTER ERROR:",
            type(exc).__name__,
        )

        decision = _resolve_semantic_decision(
            text=text,
            parsed=None,
            default_threshold=default_threshold,
            ambiguous_inventory_threshold=(
                ambiguous_threshold
            ),
        )

        decision = SemanticRoutingDecision(
            route=decision.route,
            intent=decision.intent,
            confidence=decision.confidence,
            threshold=decision.threshold,
            reason="semantic_call_error",
        )

        _log_semantic_decision(decision)
        return decision.route

    decision = _resolve_semantic_decision(
        text=text,
        parsed=parsed,
        default_threshold=default_threshold,
        ambiguous_inventory_threshold=(
            ambiguous_threshold
        ),
    )

    _log_semantic_decision(decision)

    return decision.route

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
    original_text: str | None = None,
) -> str:
    if route.query_type == "inventory_clarification":
        return handle_inventory_query(
            query_type=route.query_type,
            merchant_id=merchant_id,
            db=db,
        )

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
            original_text=original_text,
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
