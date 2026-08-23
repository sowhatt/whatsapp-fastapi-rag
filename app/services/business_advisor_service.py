from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.adaptive_forecast_service import (
    build_adaptive_month_forecast,
)
from app.services.financial_intelligence_service import (
    get_financial_intelligence,
)
from app.services.inventory_intelligence_service import (
    get_inventory_intelligence,
)
from app.services.replenishment_service import (
    build_replenishment_recommendations,
)


@dataclass
class BusinessAdvice:
    priority: str
    code: str
    title: str
    message: str
    action: str


@dataclass
class BusinessAdvisorResult:
    merchant_id: int

    revenue: int
    gross_margin: int
    gross_margin_rate: float

    forecast_revenue: int
    forecast_margin: int
    forecast_trajectory: str
    forecast_confidence: str

    stock_value: int
    customer_debt: int
    supplier_debt: int

    advices: list[BusinessAdvice] = field(
        default_factory=list
    )


def _money(value: int | float) -> str:
    return (
        f"{int(value):,}"
        .replace(",", " ")
        + " FCFA"
    )


def build_business_advisor(
    *,
    merchant_id: int,
    db: Session,
) -> BusinessAdvisorResult:

    financial = get_financial_intelligence(
        merchant_id=merchant_id,
        db=db,
    )

    inventory = get_inventory_intelligence(
        merchant_id=merchant_id,
        db=db,
    )

    forecast = build_adaptive_month_forecast(
        merchant_id=merchant_id,
        db=db,
    )

    replenishments = (
        build_replenishment_recommendations(
            merchant_id=merchant_id,
            db=db,
        )
    )

    result = BusinessAdvisorResult(
        merchant_id=merchant_id,

        revenue=financial.revenue,
        gross_margin=financial.gross_margin,
        gross_margin_rate=
            financial.gross_margin_rate,

        forecast_revenue=
            forecast.revenue.baseline,

        forecast_margin=
            forecast.gross_margin.baseline,

        forecast_trajectory=
            forecast.trajectory,

        forecast_confidence=
            forecast.confidence,

        stock_value=
            financial.stock_value,

        customer_debt=
            financial.customer_debt,

        supplier_debt=
            financial.supplier_debt,
    )

    # ======================================================
    # 1. RENTABILITE
    # ======================================================

    if financial.gross_margin_rate < 10:

        result.advices.append(
            BusinessAdvice(
                priority="critical",
                code="VERY_LOW_MARGIN",
                title="Rentabilité insuffisante",
                message=(
                    "Ton taux de marge brute est seulement "
                    f"de {financial.gross_margin_rate:.2f} %."
                ),
                action=(
                    "Vérifie en priorité les prix d'achat "
                    "et les prix de vente des produits "
                    "les moins rentables."
                ),
            )
        )

    elif financial.gross_margin_rate < 20:

        result.advices.append(
            BusinessAdvice(
                priority="warning",
                code="LOW_MARGIN",
                title="Marge à surveiller",
                message=(
                    "Ton taux de marge brute est de "
                    f"{financial.gross_margin_rate:.2f} %."
                ),
                action=(
                    "Évite les remises excessives et "
                    "surveille les produits à faible marge."
                ),
            )
        )

    # ======================================================
    # 2. FORECAST
    # ======================================================

    if forecast.trajectory in {
        "forte_acceleration",
        "acceleration",
    }:

        result.advices.append(
            BusinessAdvice(
                priority="positive",
                code="SALES_ACCELERATION",
                title="Les ventes accélèrent",
                message=(
                    "La tendance récente indique une "
                    "accélération de l'activité."
                ),
                action=(
                    "Sécurise le stock des produits "
                    "qui tournent rapidement."
                ),
            )
        )

    elif forecast.trajectory in {
        "forte_baisse",
        "ralentissement",
    }:

        result.advices.append(
            BusinessAdvice(
                priority="warning",
                code="SALES_SLOWDOWN",
                title="Ralentissement des ventes",
                message=(
                    "La tendance récente montre un "
                    "ralentissement de l'activité."
                ),
                action=(
                    "Réduis les nouveaux achats non urgents "
                    "et surveille les stocks lents."
                ),
            )
        )

    # ======================================================
    # 3. RUPTURES ET REAPPROVISIONNEMENT
    # ======================================================

    for recommendation in replenishments[:3]:

        unit = (
            recommendation.unit
            or "unités"
        )

        result.advices.append(
            BusinessAdvice(
                priority=(
                    "critical"
                    if recommendation.urgency
                    == "critical"
                    else "warning"
                ),
                code="REPLENISHMENT",
                title=(
                    "Réapprovisionnement "
                    f"{recommendation.product_name}"
                ),
                message=(
                    f"Stock actuel : "
                    f"{recommendation.stock} {unit}. "
                    f"Couverture : "
                    f"{recommendation.days_of_cover or 0:.0f} "
                    "jours."
                ),
                action=(
                    f"Commander environ "
                    f"{recommendation.recommended_quantity} "
                    f"{unit}."
                ),
            )
        )

    # ======================================================
    # 4. SURSTOCK / CAPITAL IMMOBILISE
    # ======================================================

    if financial.stock_value > 0:

        slow_items = [
            item
            for item in inventory
            if item.status in {
                "slow",
                "dormant",
            }
        ]

        slow_items.sort(
            key=lambda item: item.stock_value,
            reverse=True,
        )

        if slow_items:

            top = slow_items[0]

            concentration = (
                top.stock_value
                / financial.stock_value
                * 100
            )

            if concentration >= 20:

                result.advices.append(
                    BusinessAdvice(
                        priority="warning",
                        code="CAPITAL_LOCKED",
                        title=(
                            "Capital immobilisé dans le stock"
                        ),
                        message=(
                            f"{top.product_name} immobilise "
                            f"{_money(top.stock_value)}, "
                            f"soit {concentration:.1f} % "
                            "de la valeur du stock."
                        ),
                        action=(
                            "Évite de renforcer ce stock "
                            "tant que sa rotation reste faible."
                        ),
                    )
                )

    # ======================================================
    # 5. CREANCES / DETTES
    # ======================================================

    if (
        financial.supplier_debt
        > financial.customer_debt
        and financial.supplier_debt > 0
    ):

        gap = (
            financial.supplier_debt
            - financial.customer_debt
        )

        result.advices.append(
            BusinessAdvice(
                priority="info",
                code="WORKING_CAPITAL_GAP",
                title="Écart de trésorerie commerciale",
                message=(
                    "Les dettes fournisseurs dépassent "
                    "les créances clients de "
                    f"{_money(gap)}."
                ),
                action=(
                    "Préserve suffisamment de trésorerie "
                    "pour les prochains règlements."
                ),
            )
        )

    # ======================================================
    # TRI PAR PRIORITE
    # ======================================================

    priorities = {
        "critical": 0,
        "warning": 1,
        "info": 2,
        "positive": 3,
    }

    result.advices.sort(
        key=lambda advice: priorities.get(
            advice.priority,
            99,
        )
    )

    return result


def render_business_advisor(
    result: BusinessAdvisorResult,
) -> str:

    icons = {
        "critical": "🔴",
        "warning": "🟠",
        "info": "🔵",
        "positive": "🟢",
    }

    lines = [
        "🧠 Conseiller Business Whatzabi",
        "",
        "📊 Situation cumulée — historique enregistré",
        (
            "CA : "
            f"{_money(result.revenue)}"
        ),
        (
            "Marge brute : "
            f"{_money(result.gross_margin)} "
            f"({result.gross_margin_rate:.2f} %)"
        ),
        (
            "Stock : "
            f"{_money(result.stock_value)}"
        ),
        "",
        "🔮 Projection — fin du mois en cours",
        (
            "CA fin de mois : "
            f"{_money(result.forecast_revenue)}"
        ),
        (
            "Marge projetée : "
            f"{_money(result.forecast_margin)}"
        ),
        (
            "Confiance forecast : "
            f"{result.forecast_confidence}"
        ),
    ]

    if not result.advices:

        lines.extend([
            "",
            "✅ Aucun point d'attention majeur.",
        ])

        return "\n".join(lines)

    lines.extend([
        "",
        "🎯 Priorités recommandées",
        "",
    ])

    for index, advice in enumerate(
        result.advices[:6],
        start=1,
    ):

        icon = icons.get(
            advice.priority,
            "•",
        )

        lines.extend([
            f"{index}. {icon} {advice.title}",
            advice.message,
            f"➡️ {advice.action}",
            "",
        ])

    lines.append(
        "ℹ️ Recommandations calculées à partir "
        "de tes données commerciales actuelles."
    )

    return "\n".join(lines)


def business_advisor_to_memory(
    result: BusinessAdvisorResult,
) -> dict:
    return {
        "merchant_id": result.merchant_id,
        "revenue": result.revenue,
        "gross_margin": result.gross_margin,
        "gross_margin_rate": result.gross_margin_rate,
        "forecast_revenue": result.forecast_revenue,
        "forecast_margin": result.forecast_margin,
        "forecast_trajectory": result.forecast_trajectory,
        "forecast_confidence": result.forecast_confidence,
        "stock_value": result.stock_value,
        "customer_debt": result.customer_debt,
        "supplier_debt": result.supplier_debt,
        "advices": [
            {
                "priority": advice.priority,
                "code": advice.code,
                "title": advice.title,
                "message": advice.message,
                "action": advice.action,
            }
            for advice in result.advices
        ],
    }
