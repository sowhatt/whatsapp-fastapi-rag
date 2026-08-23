import re

from sqlalchemy.orm import Session

from app.services.inventory_intelligence_service import (
    get_inventory_intelligence,
    render_inventory_intelligence,
)
from app.services.replenishment_service import (
    build_replenishment_recommendations,
    render_replenishment_recommendations,
)


def extract_replenishment_product(text: str) -> str | None:
    value = " ".join(text.lower().split()).strip(" .!?")

    patterns = [
        r"combien de (.+?) dois-je (?:commander|acheter|racheter)",
        r"combien de (.+?) (?:commander|acheter|racheter)",
        r"quelle quantité de (.+?) dois-je (?:commander|acheter)",
        r"quelle quantite de (.+?) dois-je (?:commander|acheter)",
        r"réapprovisionner (?:en )?(.+)$",
        r"reapprovisionner (?:en )?(.+)$",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            re.IGNORECASE,
        )

        if match:
            product = match.group(1).strip()

            product = re.sub(
                r"\\b(?:pour|sur)\\s+\\d+\\s+jours?$",
                "",
                product,
            ).strip()

            if product:
                return product

    return None


def detect_inventory_query(text: str) -> str | None:
    value = " ".join(text.lower().split()).strip(" .!?")

    patterns = [
        (
            r"(rotation|roulement).*stock|"
            r"(analyse|intelligence).*stock",
            "inventory_overview",
        ),
        (
            r"(produits?|articles?).*"
            r"(dorment|dormants?|ne (se )?vendent pas|"
            r"rotation lente|tournent lentement)",
            "slow_movers",
        ),
        (
            r"(produits?|articles?).*"
            r"(rupture|risquent.*rupture|bient[oô]t fini|"
            r"bient[oô]t épuisé|bient[oô]t epuise)",
            "stockout_risk",
        ),
        (
            r"(produits?|articles?).*"
            r"(tournent vite|rotation rapide|"
            r"se vendent le plus vite)",
            "fast_movers",
        ),
        (
            r"(que|quoi).*(recommander|réapprovisionner|"
            r"reapprovisionner|racheter)|"
            r"(besoin|suggestion).*réappro",
            "replenishment_candidates",
        ),
    ]

    for pattern, query_type in patterns:
        if re.search(pattern, value, re.IGNORECASE):
            return query_type

    return None


def _money(value: int | float) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def render_product_replenishment(
    *,
    product_name: str,
    merchant_id: int,
    db: Session,
) -> str:
    recommendations = (
        build_replenishment_recommendations(
            merchant_id=merchant_id,
            db=db,
        )
    )

    normalized = product_name.lower().strip()

    match = next(
        (
            item
            for item in recommendations
            if item.product_name.lower() == normalized
        ),
        None,
    )

    if match is None:
        partial = [
            item
            for item in recommendations
            if normalized in item.product_name.lower()
            or item.product_name.lower() in normalized
        ]

        if len(partial) == 1:
            match = partial[0]

    if match is None:
        return (
            f"ℹ️ Aucun réapprovisionnement calculé "
            f"pour {product_name} actuellement."
        )

    unit = match.unit or "unités"

    lines = [
        f"📦 Prévision — {match.product_name}",
        "",
        f"Stock actuel : {match.stock} {unit}",
        f"Ventes 30 jours : {match.sold_30d}",
        f"Demande moyenne : "
        f"{match.daily_demand:.2f}/jour",
    ]

    if match.days_of_cover is not None:
        lines.append(
            f"Couverture actuelle : "
            f"~{match.days_of_cover:.0f} jours"
        )

    lines.extend([
        f"Stock cible : {match.target_stock} {unit}",
        "",
        f"➡️ Commander environ "
        f"{match.recommended_quantity} {unit}",
        "",
        "ℹ️ Objectif actuel : "
        "30 jours de vente + 7 jours de sécurité.",
    ])

    return "\\n".join(lines)


def handle_inventory_query(
    *,
    query_type: str,
    merchant_id: int,
    db: Session,
) -> str:
    metrics = get_inventory_intelligence(
        merchant_id=merchant_id,
        db=db,
    )

    if query_type == "inventory_overview":
        return render_inventory_intelligence(metrics)

    if query_type == "slow_movers":
        items = [
            item for item in metrics
            if item.status in {"slow", "dormant"}
        ]

        if not items:
            return "✅ Aucun stock à rotation lente détecté."

        items.sort(
            key=lambda item: item.stock_value,
            reverse=True,
        )

        lines = [
            "🐢 Produits à rotation lente",
            "",
        ]

        for item in items[:10]:
            if item.days_of_cover is None:
                cover = "aucune vente sur 30 jours"
            else:
                cover = (
                    f"~{item.days_of_cover:.0f} jours de stock"
                )

            lines.append(
                f"• {item.product_name} : "
                f"{_money(item.stock_value)} — {cover}"
            )

        return "\n".join(lines)

    if query_type == "stockout_risk":
        items = [
            item for item in metrics
            if item.status in {
                "rupture",
                "rupture_risk",
            }
        ]

        if not items:
            return "✅ Aucun risque de rupture immédiat détecté."

        items.sort(
            key=lambda item: (
                item.days_of_cover
                if item.days_of_cover is not None
                else -1
            )
        )

        lines = [
            "⚠️ Risques de rupture",
            "",
        ]

        for item in items[:10]:
            if item.stock <= 0:
                lines.append(
                    f"🔴 {item.product_name} : rupture de stock"
                )
            else:
                lines.append(
                    f"🟠 {item.product_name} : "
                    f"{item.stock} {item.unit or 'unités'} — "
                    f"~{item.days_of_cover:.0f} jours"
                )

        return "\n".join(lines)

    if query_type == "fast_movers":
        items = [
            item for item in metrics
            if item.status == "fast"
        ]

        if not items:
            return "ℹ️ Aucun produit classé en rotation rapide actuellement."

        items.sort(
            key=lambda item: item.velocity_30d,
            reverse=True,
        )

        lines = [
            "🚀 Produits à rotation rapide",
            "",
        ]

        for item in items[:10]:
            lines.append(
                f"• {item.product_name} : "
                f"{item.sold_30d} vendus sur 30 jours — "
                f"{item.velocity_30d:.2f}/jour — "
                f"~{item.days_of_cover:.0f} jours de stock"
            )

        return "\n".join(lines)

    if query_type == "replenishment_candidates":
        recommendations = (
            build_replenishment_recommendations(
                merchant_id=merchant_id,
                db=db,
            )
        )

        return render_replenishment_recommendations(
            recommendations
        )

    raise ValueError(
        f"Question stock inconnue : {query_type}"
    )
