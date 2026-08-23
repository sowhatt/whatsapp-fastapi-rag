from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class InventoryMetric:
    product_id: int
    product_name: str
    unit: str | None
    stock: int
    stock_value: int
    sold_7d: int
    sold_30d: int
    sold_90d: int
    velocity_30d: float
    days_of_cover: float | None
    status: str


def get_inventory_intelligence(
    *,
    merchant_id: int,
    db: Session,
) -> list[InventoryMetric]:

    now = datetime.now()

    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)
    since_90d = now - timedelta(days=90)

    rows = db.execute(
        text("""
            WITH sales_window AS (
                SELECT
                    si.product_id,

                    SUM(
                        CASE
                            WHEN s.created_at >= :since_7d
                            THEN si.quantity
                            ELSE 0
                        END
                    ) AS sold_7d,

                    SUM(
                        CASE
                            WHEN s.created_at >= :since_30d
                            THEN si.quantity
                            ELSE 0
                        END
                    ) AS sold_30d,

                    SUM(
                        CASE
                            WHEN s.created_at >= :since_90d
                            THEN si.quantity
                            ELSE 0
                        END
                    ) AS sold_90d

                FROM sales s

                JOIN sale_items si
                  ON si.sale_id = s.id

                WHERE s.merchant_id = :merchant_id
                  AND s.status <> 'cancelled'

                GROUP BY si.product_id
            )

            SELECT
                stock.product_id,
                stock.product_name,
                stock.unit,
                stock.stock,
                stock.stock_value,

                COALESCE(sw.sold_7d, 0) AS sold_7d,
                COALESCE(sw.sold_30d, 0) AS sold_30d,
                COALESCE(sw.sold_90d, 0) AS sold_90d

            FROM mv_stock_analytics stock

            LEFT JOIN sales_window sw
              ON sw.product_id = stock.product_id

            WHERE stock.merchant_id = :merchant_id

            ORDER BY stock.stock_value DESC
        """),
        {
            "merchant_id": merchant_id,
            "since_7d": since_7d,
            "since_30d": since_30d,
            "since_90d": since_90d,
        },
    ).mappings().all()

    result = []

    for row in rows:
        stock = int(row["stock"] or 0)
        sold_30d = int(row["sold_30d"] or 0)

        velocity_30d = (
            sold_30d / 30
            if sold_30d > 0
            else 0.0
        )

        days_of_cover = (
            stock / velocity_30d
            if velocity_30d > 0
            else None
        )

        if stock <= 0:
            status = "rupture"

        elif days_of_cover is None:
            status = "dormant"

        elif days_of_cover < 7:
            status = "rupture_risk"

        elif days_of_cover <= 30:
            status = "fast"

        elif days_of_cover <= 90:
            status = "normal"

        else:
            status = "slow"

        result.append(
            InventoryMetric(
                product_id=int(row["product_id"]),
                product_name=str(row["product_name"]),
                unit=row["unit"],
                stock=stock,
                stock_value=int(row["stock_value"] or 0),
                sold_7d=int(row["sold_7d"] or 0),
                sold_30d=sold_30d,
                sold_90d=int(row["sold_90d"] or 0),
                velocity_30d=round(
                    velocity_30d,
                    3,
                ),
                days_of_cover=(
                    round(days_of_cover, 1)
                    if days_of_cover is not None
                    else None
                ),
                status=status,
            )
        )

    return result


def _money(value: int | float) -> str:
    return (
        f"{int(value):,}"
        .replace(",", " ")
        + " FCFA"
    )


def render_inventory_intelligence(
    metrics: list[InventoryMetric],
) -> str:

    if not metrics:
        return "📦 Aucun produit à analyser."

    total_value = sum(
        item.stock_value
        for item in metrics
    )

    slow = [
        item
        for item in metrics
        if item.status in {"slow", "dormant"}
    ]

    rupture_risk = [
        item
        for item in metrics
        if item.status in {
            "rupture",
            "rupture_risk",
        }
    ]

    fast = [
        item
        for item in metrics
        if item.status == "fast"
    ]

    lines = [
        "📦 Intelligence stock",
        "",
        f"Valeur totale du stock : {_money(total_value)}",
    ]

    if slow:
        lines.extend([
            "",
            "🔴 Rotation lente / stock dormant",
        ])

        for item in slow[:5]:
            if item.days_of_cover is None:
                cover = "aucune vente récente"
            else:
                cover = (
                    f"{item.days_of_cover:.0f} jours "
                    "de couverture"
                )

            lines.append(
                f"• {item.product_name} : "
                f"{_money(item.stock_value)} — "
                f"{cover}"
            )

    if rupture_risk:
        lines.extend([
            "",
            "⚠️ Risque de rupture",
        ])

        for item in rupture_risk[:5]:
            if item.days_of_cover is None:
                cover = "stock épuisé"
            else:
                cover = (
                    f"~{item.days_of_cover:.0f} jours"
                )

            lines.append(
                f"• {item.product_name} : "
                f"{cover}"
            )

    if fast:
        lines.extend([
            "",
            "🟢 Rotation rapide",
        ])

        for item in fast[:5]:
            lines.append(
                f"• {item.product_name} : "
                f"{item.sold_30d} vendus / 30 j — "
                f"{item.days_of_cover:.0f} jours "
                "de stock"
            )

    return "\n".join(lines)
