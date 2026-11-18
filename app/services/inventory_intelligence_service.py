from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil

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

    # Champs Stock Intelligent V1.
    # Valeurs par défaut pour conserver la compatibilité
    # avec le moteur historique merchant-wide.
    threshold: int = 0
    purchase_price: int = 0
    price: int = 0

    revenue_30d: int = 0
    cogs_30d: int = 0
    gross_margin_30d: int = 0

    rotation_proxy_30d: float | None = None

    last_sale_at: datetime | None = None
    days_since_last_sale: int | None = None

    target_stock: int = 0
    recommended_quantity: int = 0


def _resolve_shop_id(db: Session) -> int | None:
    shop_id = (
        db.info.get("pwa_shop_id")
        or db.info.get("resolved_shop_id")
    )

    return (
        int(shop_id)
        if shop_id is not None
        else None
    )



def _get_legacy_inventory_intelligence(
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



def get_inventory_intelligence(
    *,
    merchant_id: int,
    db: Session,
    shop_id: int | None = None,
    target_cover_days: int = 30,
    safety_days: int = 7,
) -> list[InventoryMetric]:
    """
    Intelligence stock opérationnelle par boutique.

    Important :
    rotation_proxy_30d = quantité vendue sur 30 jours / stock actuel.

    Ce n'est PAS une rotation comptable basée sur le stock moyen.
    """

    resolved_shop_id = (
        int(shop_id)
        if shop_id is not None
        else _resolve_shop_id(db)
    )

    # Compatibilité WhatsApp / BI historique :
    # hors contexte boutique, on conserve le moteur merchant-wide.
    if resolved_shop_id is None:
        return _get_legacy_inventory_intelligence(
            merchant_id=merchant_id,
            db=db,
        )

    now = datetime.now()

    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)
    since_90d = now - timedelta(days=90)

    rows = db.execute(
        text(
            """
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
                    ) AS sold_90d,

                    SUM(
                        CASE
                            WHEN s.created_at >= :since_30d
                            THEN si.line_total
                            ELSE 0
                        END
                    ) AS revenue_30d,

                    SUM(
                        CASE
                            WHEN s.created_at >= :since_30d
                            THEN
                                si.quantity
                                * COALESCE(
                                    si.unit_cost_snapshot,
                                    0
                                )
                            ELSE 0
                        END
                    ) AS cogs_30d,

                    MAX(s.created_at) AS last_sale_at

                FROM sales s

                JOIN shop_operations so
                  ON so.entity_type = 'sale'
                 AND so.entity_id = s.id
                 AND so.merchant_id = s.merchant_id
                 AND so.shop_id = :shop_id

                JOIN sale_items si
                  ON si.sale_id = s.id

                WHERE s.merchant_id = :merchant_id
                  AND s.status <> 'cancelled'
                  AND s.created_at >= :since_90d

                GROUP BY si.product_id
            )

            SELECT
                stock.product_id,
                stock.product_name,
                stock.unit,
                stock.stock,
                stock.threshold,
                stock.purchase_price,
                stock.price,
                stock.stock_value,

                COALESCE(sw.sold_7d, 0) AS sold_7d,
                COALESCE(sw.sold_30d, 0) AS sold_30d,
                COALESCE(sw.sold_90d, 0) AS sold_90d,

                COALESCE(sw.revenue_30d, 0)
                    AS revenue_30d,

                COALESCE(sw.cogs_30d, 0)
                    AS cogs_30d,

                sw.last_sale_at

            FROM mv_stock_analytics_by_shop stock

            LEFT JOIN sales_window sw
              ON sw.product_id = stock.product_id

            WHERE stock.merchant_id = :merchant_id
              AND stock.shop_id = :shop_id

            ORDER BY
                stock.stock_value DESC,
                stock.product_name
            """
        ),
        {
            "merchant_id": merchant_id,
            "shop_id": resolved_shop_id,
            "since_7d": since_7d,
            "since_30d": since_30d,
            "since_90d": since_90d,
        },
    ).mappings().all()

    result: list[InventoryMetric] = []

    for row in rows:
        stock = int(row["stock"] or 0)
        threshold = int(row["threshold"] or 0)

        sold_7d = int(row["sold_7d"] or 0)
        sold_30d = int(row["sold_30d"] or 0)
        sold_90d = int(row["sold_90d"] or 0)

        revenue_30d = int(row["revenue_30d"] or 0)
        cogs_30d = int(row["cogs_30d"] or 0)

        gross_margin_30d = revenue_30d - cogs_30d

        velocity_30d = (
            sold_30d / 30.0
            if sold_30d > 0
            else 0.0
        )

        days_of_cover = (
            stock / velocity_30d
            if velocity_30d > 0
            else None
        )

        rotation_proxy_30d = (
            sold_30d / stock
            if stock > 0
            else None
        )

        last_sale_at = row["last_sale_at"]

        days_since_last_sale = (
            max(
                0,
                (now - last_sale_at).days,
            )
            if last_sale_at is not None
            else None
        )

        target_stock = (
            ceil(
                velocity_30d
                * (
                    max(target_cover_days, 1)
                    + max(safety_days, 0)
                )
            )
            if velocity_30d > 0
            else 0
        )

        recommended_quantity = max(
            0,
            target_stock - stock,
        )

        #
        # Classification métier V1.
        #
        # Priorité :
        # 1. rupture
        # 2. besoin de réapprovisionnement
        # 3. dormant
        # 4. rotation lente
        # 5. rotation rapide
        # 6. normal
        #
        if stock <= 0:
            status = "out_of_stock"

        elif (
            velocity_30d > 0
            and (
                stock <= threshold
                or (
                    days_of_cover is not None
                    and days_of_cover < 7
                )
            )
        ):
            status = "replenish"

        elif sold_90d == 0:
            status = "dormant"

        elif (
            sold_30d == 0
            or (
                days_since_last_sale is not None
                and days_since_last_sale >= 30
            )
            or (
                days_of_cover is not None
                and days_of_cover > 90
            )
        ):
            status = "slow"

        elif (
            velocity_30d > 0
            and days_of_cover is not None
            and days_of_cover <= 30
        ):
            status = "fast"

        else:
            status = "normal"

        result.append(
            InventoryMetric(
                product_id=int(row["product_id"]),
                product_name=str(row["product_name"]),
                unit=row["unit"],

                stock=stock,
                threshold=threshold,

                purchase_price=int(
                    row["purchase_price"] or 0
                ),
                price=int(row["price"] or 0),

                stock_value=int(
                    row["stock_value"] or 0
                ),

                sold_7d=sold_7d,
                sold_30d=sold_30d,
                sold_90d=sold_90d,

                revenue_30d=revenue_30d,
                cogs_30d=cogs_30d,
                gross_margin_30d=gross_margin_30d,

                velocity_30d=round(
                    velocity_30d,
                    3,
                ),

                days_of_cover=(
                    round(days_of_cover, 1)
                    if days_of_cover is not None
                    else None
                ),

                rotation_proxy_30d=(
                    round(rotation_proxy_30d, 3)
                    if rotation_proxy_30d is not None
                    else None
                ),

                last_sale_at=last_sale_at,
                days_since_last_sale=days_since_last_sale,

                target_stock=target_stock,
                recommended_quantity=recommended_quantity,

                status=status,
            )
        )

    return result


def summarize_inventory_intelligence(
    metrics: list[InventoryMetric],
) -> dict[str, int]:
    return {
        "total_products": len(metrics),
        "out_of_stock": sum(
            item.status == "out_of_stock"
            for item in metrics
        ),
        "replenish": sum(
            item.status == "replenish"
            for item in metrics
        ),
        "fast": sum(
            item.status == "fast"
            for item in metrics
        ),
        "normal": sum(
            item.status == "normal"
            for item in metrics
        ),
        "slow": sum(
            item.status == "slow"
            for item in metrics
        ),
        "dormant": sum(
            item.status == "dormant"
            for item in metrics
        ),
        "stock_value": sum(
            item.stock_value
            for item in metrics
        ),
        "recommended_units": sum(
            item.recommended_quantity
            for item in metrics
        ),
    }


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

    summary = summarize_inventory_intelligence(
        metrics
    )

    lines = [
        "📦 Intelligence stock",
        "",
        (
            "Valeur totale du stock : "
            f"{_money(summary['stock_value'])}"
        ),
        (
            "À commander : "
            f"{summary['replenish']} produit(s)"
        ),
        (
            "Ruptures : "
            f"{summary['out_of_stock']}"
        ),
        (
            "Dormants : "
            f"{summary['dormant']}"
        ),
    ]

    priority = [
        item
        for item in metrics
        if item.status in {
            "out_of_stock",
            "replenish",
        }
    ]

    if priority:
        lines.extend([
            "",
            "⚠️ Priorités",
        ])

        priority.sort(
            key=lambda item: (
                item.status != "out_of_stock",
                item.days_of_cover
                if item.days_of_cover is not None
                else -1,
            )
        )

        for item in priority[:5]:
            if item.status == "out_of_stock":
                lines.append(
                    f"• {item.product_name} : rupture"
                )
            else:
                lines.append(
                    f"• {item.product_name} : "
                    f"{item.stock} "
                    f"{item.unit or 'unités'} — "
                    f"~{item.days_of_cover:.0f} jours — "
                    f"commander ~"
                    f"{item.recommended_quantity}"
                )

    dormant = [
        item
        for item in metrics
        if item.status == "dormant"
    ]

    if dormant:
        dormant.sort(
            key=lambda item: item.stock_value,
            reverse=True,
        )

        lines.extend([
            "",
            "💤 Stock dormant",
        ])

        for item in dormant[:5]:
            lines.append(
                f"• {item.product_name} : "
                f"{_money(item.stock_value)} immobilisés"
            )

    return "\n".join(lines)
