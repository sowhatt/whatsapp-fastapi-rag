from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session


def create_inventory_snapshot(
    *,
    merchant_id: int,
    db: Session,
    snapshot_date: date | None = None,
) -> int:
    """
    Snapshot quotidien du stock et de l'activité produit.

    Idempotent :
    un second passage le même jour met à jour les lignes existantes.

    Sources :
    - stock actuel : mv_stock_analytics
    - ventes du jour : sales + sale_items
    - ventes annulées exclues
    """

    day = snapshot_date or date.today()

    start_at = datetime.combine(
        day,
        time.min,
    )

    end_at = start_at + timedelta(days=1)

    result = db.execute(
        text("""
            INSERT INTO fact_inventory_daily_snapshot (
                snapshot_date,
                merchant_id,
                product_id,
                product_name,
                unit,
                stock_quantity,
                unit_cost,
                stock_value,
                potential_sales_value,
                quantity_sold_day,
                sales_revenue_day,
                cogs_day
            )

            SELECT
                :snapshot_date,
                stock.merchant_id,
                stock.product_id,
                stock.product_name,
                stock.unit,

                COALESCE(stock.stock, 0),

                COALESCE(
                    stock.purchase_price,
                    0
                ),

                COALESCE(
                    stock.stock_value,
                    0
                ),

                COALESCE(
                    stock.potential_sales_value,
                    0
                ),

                COALESCE(
                    daily.quantity_sold_day,
                    0
                ),

                COALESCE(
                    daily.sales_revenue_day,
                    0
                ),

                COALESCE(
                    daily.cogs_day,
                    0
                )

            FROM mv_stock_analytics stock

            LEFT JOIN (
                SELECT
                    s.merchant_id,
                    si.product_id,

                    SUM(
                        si.quantity
                    ) AS quantity_sold_day,

                    SUM(
                        si.line_total
                    ) AS sales_revenue_day,

                    SUM(
                        si.quantity
                        * COALESCE(
                            si.unit_cost_snapshot,
                            0
                        )
                    ) AS cogs_day

                FROM sales s

                JOIN sale_items si
                  ON si.sale_id = s.id

                WHERE s.merchant_id = :merchant_id

                  AND s.status <> 'cancelled'

                  AND s.created_at >= :start_at

                  AND s.created_at < :end_at

                GROUP BY
                    s.merchant_id,
                    si.product_id
            ) daily

              ON daily.merchant_id =
                    stock.merchant_id

             AND daily.product_id =
                    stock.product_id

            WHERE stock.merchant_id =
                :merchant_id

            ON CONFLICT (
                snapshot_date,
                merchant_id,
                product_id
            )

            DO UPDATE SET

                product_name =
                    EXCLUDED.product_name,

                unit =
                    EXCLUDED.unit,

                stock_quantity =
                    EXCLUDED.stock_quantity,

                unit_cost =
                    EXCLUDED.unit_cost,

                stock_value =
                    EXCLUDED.stock_value,

                potential_sales_value =
                    EXCLUDED.potential_sales_value,

                quantity_sold_day =
                    EXCLUDED.quantity_sold_day,

                sales_revenue_day =
                    EXCLUDED.sales_revenue_day,

                cogs_day =
                    EXCLUDED.cogs_day
        """),
        {
            "snapshot_date": day,
            "merchant_id": merchant_id,
            "start_at": start_at,
            "end_at": end_at,
        },
    )

    db.commit()

    return result.rowcount or 0
