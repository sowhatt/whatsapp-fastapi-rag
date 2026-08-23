from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.inventory_intelligence_service import (
    InventoryMetric,
    get_inventory_intelligence,
)


@dataclass
class ReplenishmentRecommendation:
    product_id: int
    product_name: str
    unit: str | None

    stock: int

    sold_30d: int
    daily_demand: float

    target_days: int
    safety_days: int

    target_stock: int
    recommended_quantity: int

    days_of_cover: float | None
    urgency: str


def build_replenishment_recommendations(
    *,
    merchant_id: int,
    db: Session,
    target_days: int = 30,
    safety_days: int = 7,
) -> list[ReplenishmentRecommendation]:

    metrics = get_inventory_intelligence(
        merchant_id=merchant_id,
        db=db,
    )

    recommendations = []

    for item in metrics:
        daily_demand = item.velocity_30d

        if daily_demand <= 0:
            continue

        coverage_target = (
            target_days + safety_days
        )

        target_stock = round(
            daily_demand * coverage_target
        )

        recommended_quantity = max(
            0,
            target_stock - item.stock,
        )

        if recommended_quantity <= 0:
            continue

        if item.stock <= 0:
            urgency = "critical"

        elif (
            item.days_of_cover is not None
            and item.days_of_cover <= 7
        ):
            urgency = "high"

        elif (
            item.days_of_cover is not None
            and item.days_of_cover <= 15
        ):
            urgency = "medium"

        else:
            urgency = "low"

        recommendations.append(
            ReplenishmentRecommendation(
                product_id=item.product_id,
                product_name=item.product_name,
                unit=item.unit,
                stock=item.stock,
                sold_30d=item.sold_30d,
                daily_demand=round(
                    daily_demand,
                    2,
                ),
                target_days=target_days,
                safety_days=safety_days,
                target_stock=target_stock,
                recommended_quantity=
                    recommended_quantity,
                days_of_cover=item.days_of_cover,
                urgency=urgency,
            )
        )

    priority = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }

    recommendations.sort(
        key=lambda item: (
            priority[item.urgency],
            -item.recommended_quantity,
        )
    )

    return recommendations


def render_replenishment_recommendations(
    recommendations:
        list[ReplenishmentRecommendation],
) -> str:

    if not recommendations:
        return (
            "✅ Aucun réapprovisionnement "
            "n'est nécessaire selon la demande récente."
        )

    lines = [
        "📦 Prévision de réapprovisionnement",
        "",
        "Objectif : 30 jours de vente "
        "+ 7 jours de sécurité",
        "",
    ]

    icons = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🔵",
    }

    for item in recommendations[:10]:
        icon = icons.get(
            item.urgency,
            "•",
        )

        unit = (
            item.unit
            or "unités"
        )

        lines.extend([
            f"{icon} {item.product_name}",
            f"Stock actuel : "
            f"{item.stock} {unit}",
            f"Ventes 30 jours : "
            f"{item.sold_30d}",
            f"Demande moyenne : "
            f"{item.daily_demand:.2f}/jour",
        ])

        if item.days_of_cover is not None:
            lines.append(
                "Couverture actuelle : "
                f"~{item.days_of_cover:.0f} jours"
            )

        lines.extend([
            f"Stock cible : "
            f"{item.target_stock} {unit}",
            f"➡️ Commander environ "
            f"{item.recommended_quantity} {unit}",
            "",
        ])

    lines.append(
        "ℹ️ Prévision basée sur les ventes "
        "des 30 derniers jours."
    )

    return "\n".join(lines)
