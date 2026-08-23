
DROP MATERIALIZED VIEW IF EXISTS mv_daily_business_metrics CASCADE;

CREATE MATERIALIZED VIEW mv_daily_business_metrics AS
WITH sales_daily AS (
    SELECT
        s.merchant_id,
        DATE(s.created_at) AS business_date,
        COUNT(*) AS sales_count,
        SUM(s.total_amount) AS sales_total,
        SUM(s.paid_amount) AS sales_paid,
        SUM(s.remaining_amount) AS sales_credit
    FROM sales s
    WHERE s.status <> 'cancelled'
    GROUP BY s.merchant_id, DATE(s.created_at)
),
cogs_daily AS (
    SELECT
        s.merchant_id,
        DATE(s.created_at) AS business_date,
        SUM(si.quantity * COALESCE(si.unit_cost_snapshot, 0)) AS cogs
    FROM sales s
    JOIN sale_items si
      ON si.sale_id = s.id
    WHERE s.status <> 'cancelled'
    GROUP BY s.merchant_id, DATE(s.created_at)
),
purchases_daily AS (
    SELECT
        p.merchant_id,
        DATE(p.created_at) AS business_date,
        COUNT(*) AS purchases_count,
        SUM(p.total_amount) AS purchases_total,
        SUM(p.paid_amount) AS purchases_paid,
        SUM(p.remaining_amount) AS purchases_credit
    FROM purchases p
    WHERE p.status <> 'cancelled'
    GROUP BY p.merchant_id, DATE(p.created_at)
),
expenses_daily AS (
    SELECT
        f.merchant_id,
        DATE(f.created_at) AS business_date,
        SUM(
            CASE
                WHEN f.entry_type = 'expense'
                THEN f.amount
                ELSE 0
            END
        ) AS expenses_total
    FROM financial_entries f
    GROUP BY f.merchant_id, DATE(f.created_at)
),
all_days AS (
    SELECT merchant_id, business_date FROM sales_daily
    UNION
    SELECT merchant_id, business_date FROM purchases_daily
    UNION
    SELECT merchant_id, business_date FROM expenses_daily
)
SELECT
    d.merchant_id,
    d.business_date,

    COALESCE(s.sales_count, 0) AS sales_count,
    COALESCE(s.sales_total, 0) AS sales_total,
    COALESCE(s.sales_paid, 0) AS sales_paid,
    COALESCE(s.sales_credit, 0) AS sales_credit,

    COALESCE(p.purchases_count, 0) AS purchases_count,
    COALESCE(p.purchases_total, 0) AS purchases_total,
    COALESCE(p.purchases_paid, 0) AS purchases_paid,
    COALESCE(p.purchases_credit, 0) AS purchases_credit,

    COALESCE(e.expenses_total, 0) AS expenses_total,

    COALESCE(c.cogs, 0) AS cogs,

    COALESCE(s.sales_total, 0)
      - COALESCE(c.cogs, 0) AS gross_margin,

    COALESCE(s.sales_paid, 0)
      - COALESCE(p.purchases_paid, 0)
      - COALESCE(e.expenses_total, 0) AS net_cash_flow

FROM all_days d
LEFT JOIN sales_daily s
  ON s.merchant_id = d.merchant_id
 AND s.business_date = d.business_date

LEFT JOIN cogs_daily c
  ON c.merchant_id = d.merchant_id
 AND c.business_date = d.business_date

LEFT JOIN purchases_daily p
  ON p.merchant_id = d.merchant_id
 AND p.business_date = d.business_date

LEFT JOIN expenses_daily e
  ON e.merchant_id = d.merchant_id
 AND e.business_date = d.business_date
;

CREATE UNIQUE INDEX ux_mv_daily_business_metrics
ON mv_daily_business_metrics (
    merchant_id,
    business_date
);


DROP MATERIALIZED VIEW IF EXISTS mv_product_profitability CASCADE;

CREATE MATERIALIZED VIEW mv_product_profitability AS
SELECT
    s.merchant_id,
    si.product_id,
    p.name AS product_name,

    SUM(si.quantity) AS quantity_sold,

    SUM(si.line_total) AS sales_revenue,

    SUM(
        si.quantity * COALESCE(si.unit_cost_snapshot, 0)
    ) AS cogs,

    SUM(si.line_total)
      - SUM(
          si.quantity * COALESCE(si.unit_cost_snapshot, 0)
        ) AS gross_margin,

    CASE
        WHEN SUM(si.line_total) > 0
        THEN ROUND(
            (
                (
                    SUM(si.line_total)
                    - SUM(
                        si.quantity
                        * COALESCE(si.unit_cost_snapshot, 0)
                    )
                )::numeric
                / SUM(si.line_total)
            ) * 100,
            2
        )
        ELSE 0
    END AS gross_margin_rate,

    p.stock AS current_stock,

    p.stock * COALESCE(p.purchase_price, 0)
        AS current_stock_value

FROM sales s
JOIN sale_items si
  ON si.sale_id = s.id
JOIN products p
  ON p.id = si.product_id

WHERE s.status <> 'cancelled'

GROUP BY
    s.merchant_id,
    si.product_id,
    p.name,
    p.stock,
    p.purchase_price
;

CREATE UNIQUE INDEX ux_mv_product_profitability
ON mv_product_profitability (
    merchant_id,
    product_id
);


DROP MATERIALIZED VIEW IF EXISTS mv_currency_purchase_exposure CASCADE;

CREATE MATERIALIZED VIEW mv_currency_purchase_exposure AS
SELECT
    p.merchant_id,
    DATE_TRUNC('month', p.created_at)::date AS month,
    COALESCE(p.original_currency, 'XOF') AS original_currency,

    COUNT(*) AS purchase_count,

    SUM(
        COALESCE(p.original_amount, p.total_amount)
    ) AS original_amount_total,

    SUM(p.total_amount) AS xof_amount_total,

    AVG(
        COALESCE(p.exchange_rate, 1)
    ) AS average_exchange_rate

FROM purchases p

WHERE p.status <> 'cancelled'

GROUP BY
    p.merchant_id,
    DATE_TRUNC('month', p.created_at)::date,
    COALESCE(p.original_currency, 'XOF')
;

CREATE UNIQUE INDEX ux_mv_currency_purchase_exposure
ON mv_currency_purchase_exposure (
    merchant_id,
    month,
    original_currency
);
