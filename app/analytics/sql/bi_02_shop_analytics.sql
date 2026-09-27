-- Whatzabi BI Multi-Shop
-- Analytics scoped by merchant + shop.
-- Existing merchant-level views remain untouched.

DROP MATERIALIZED VIEW IF EXISTS mv_daily_business_metrics_by_shop CASCADE;

CREATE MATERIALIZED VIEW mv_daily_business_metrics_by_shop AS
WITH sales_daily AS (
    SELECT
        s.merchant_id,
        so.shop_id,
        DATE(s.created_at) AS business_date,
        COUNT(*) AS sales_count,
        SUM(s.total_amount) AS sales_total,
        SUM(s.paid_amount) AS sales_paid,
        SUM(s.remaining_amount) AS sales_credit
    FROM sales s
    JOIN shop_operations so
      ON so.entity_type = 'sale'
     AND so.entity_id = s.id
     AND so.merchant_id = s.merchant_id
    WHERE s.status <> 'cancelled'
    GROUP BY s.merchant_id, so.shop_id, DATE(s.created_at)
),
cogs_daily AS (
    SELECT
        s.merchant_id,
        so.shop_id,
        DATE(s.created_at) AS business_date,
        SUM(si.quantity * COALESCE(si.unit_cost_snapshot, 0)) AS cogs
    FROM sales s
    JOIN shop_operations so
      ON so.entity_type = 'sale'
     AND so.entity_id = s.id
     AND so.merchant_id = s.merchant_id
    JOIN sale_items si ON si.sale_id = s.id
    WHERE s.status <> 'cancelled'
    GROUP BY s.merchant_id, so.shop_id, DATE(s.created_at)
),
purchases_daily AS (
    SELECT
        p.merchant_id,
        so.shop_id,
        DATE(p.created_at) AS business_date,
        COUNT(*) AS purchases_count,
        SUM(p.total_amount) AS purchases_total,
        SUM(p.paid_amount) AS purchases_paid,
        SUM(p.remaining_amount) AS purchases_credit
    FROM purchases p
    JOIN shop_operations so
      ON so.entity_type = 'purchase'
     AND so.entity_id = p.id
     AND so.merchant_id = p.merchant_id
    WHERE p.status <> 'cancelled'
    GROUP BY p.merchant_id, so.shop_id, DATE(p.created_at)
),
expenses_daily AS (
    SELECT
        f.merchant_id,
        so.shop_id,
        DATE(f.created_at) AS business_date,
        SUM(
            CASE
                WHEN f.entry_type = 'expense' THEN f.amount
                ELSE 0
            END
        ) AS expenses_total
    FROM financial_entries f
    JOIN shop_operations so
      ON so.entity_type = 'financial_entry'
     AND so.entity_id = f.id
     AND so.merchant_id = f.merchant_id
    GROUP BY f.merchant_id, so.shop_id, DATE(f.created_at)
),
all_days AS (
    SELECT merchant_id, shop_id, business_date FROM sales_daily
    UNION
    SELECT merchant_id, shop_id, business_date FROM purchases_daily
    UNION
    SELECT merchant_id, shop_id, business_date FROM expenses_daily
)
SELECT
    d.merchant_id,
    d.shop_id,
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
 AND s.shop_id = d.shop_id
 AND s.business_date = d.business_date

LEFT JOIN cogs_daily c
  ON c.merchant_id = d.merchant_id
 AND c.shop_id = d.shop_id
 AND c.business_date = d.business_date

LEFT JOIN purchases_daily p
  ON p.merchant_id = d.merchant_id
 AND p.shop_id = d.shop_id
 AND p.business_date = d.business_date

LEFT JOIN expenses_daily e
  ON e.merchant_id = d.merchant_id
 AND e.shop_id = d.shop_id
 AND e.business_date = d.business_date
;

CREATE UNIQUE INDEX ux_mv_daily_business_metrics_by_shop
ON mv_daily_business_metrics_by_shop (
    merchant_id,
    shop_id,
    business_date
);


DROP MATERIALIZED VIEW IF EXISTS mv_product_profitability_by_shop CASCADE;

CREATE MATERIALIZED VIEW mv_product_profitability_by_shop AS
SELECT
    s.merchant_id,
    so.shop_id,
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

    COALESCE(inv.stock, 0) AS current_stock,

    COALESCE(inv.stock, 0)
      * COALESCE(p.purchase_price, 0)
      AS current_stock_value

FROM sales s

JOIN shop_operations so
  ON so.entity_type = 'sale'
 AND so.entity_id = s.id
 AND so.merchant_id = s.merchant_id

JOIN sale_items si
  ON si.sale_id = s.id

JOIN products p
  ON p.id = si.product_id

LEFT JOIN shop_inventories inv
  ON inv.merchant_id = s.merchant_id
 AND inv.shop_id = so.shop_id
 AND inv.product_id = si.product_id

WHERE s.status <> 'cancelled'

GROUP BY
    s.merchant_id,
    so.shop_id,
    si.product_id,
    p.name,
    inv.stock,
    p.purchase_price
;

CREATE UNIQUE INDEX ux_mv_product_profitability_by_shop
ON mv_product_profitability_by_shop (
    merchant_id,
    shop_id,
    product_id
);


DROP MATERIALIZED VIEW IF EXISTS mv_stock_analytics_by_shop CASCADE;

CREATE MATERIALIZED VIEW mv_stock_analytics_by_shop AS
SELECT
    si.merchant_id,
    si.shop_id,
    p.id AS product_id,
    p.name AS product_name,
    p.unit,

    si.stock,
    si.threshold,

    p.purchase_price,
    p.price,

    si.stock
      * COALESCE(p.purchase_price, 0)
      AS stock_value,

    si.stock
      * COALESCE(p.price, 0)
      AS potential_sales_value,

    si.stock
      * GREATEST(
          COALESCE(p.price, 0)
          - COALESCE(p.purchase_price, 0),
          0
        )
      AS potential_gross_margin,

    CASE
        WHEN si.stock <= 0 THEN 'out_of_stock'
        WHEN si.stock <= si.threshold THEN 'low_stock'
        ELSE 'normal'
    END AS stock_status

FROM shop_inventories si
JOIN products p
  ON p.id = si.product_id
 AND p.merchant_id = si.merchant_id
;

CREATE UNIQUE INDEX ux_mv_stock_analytics_by_shop
ON mv_stock_analytics_by_shop (
    merchant_id,
    shop_id,
    product_id
);


-- ============================================================
-- CUSTOMER FINANCIAL POSITION BY SHOP
-- Source of truth:
--   sales.remaining_amount + shop_operations
-- Customer.debt remains merchant-wide for legacy compatibility.
-- ============================================================

DROP MATERIALIZED VIEW IF EXISTS mv_customer_financial_position_by_shop CASCADE;

CREATE MATERIALIZED VIEW mv_customer_financial_position_by_shop AS
SELECT
    s.merchant_id,
    so.shop_id,
    s.customer_id,
    c.name AS customer_name,

    COUNT(*) FILTER (
        WHERE s.status <> 'cancelled'
    ) AS sales_count,

    COALESCE(
        SUM(s.total_amount) FILTER (
            WHERE s.status <> 'cancelled'
        ),
        0
    ) AS total_sales,

    COALESCE(
        SUM(s.paid_amount) FILTER (
            WHERE s.status <> 'cancelled'
        ),
        0
    ) AS total_paid,

    COALESCE(
        SUM(s.remaining_amount) FILTER (
            WHERE s.status <> 'cancelled'
              AND s.remaining_amount > 0
        ),
        0
    ) AS outstanding_amount,

    COALESCE(
        SUM(s.remaining_amount) FILTER (
            WHERE s.status <> 'cancelled'
              AND s.remaining_amount > 0
              AND s.due_date IS NOT NULL
              AND s.due_date < CURRENT_DATE
        ),
        0
    ) AS overdue_amount,

    MIN(s.due_date) FILTER (
        WHERE s.status <> 'cancelled'
          AND s.remaining_amount > 0
          AND s.due_date IS NOT NULL
    ) AS next_due_date

FROM sales s

JOIN shop_operations so
  ON so.entity_type = 'sale'
 AND so.entity_id = s.id
 AND so.merchant_id = s.merchant_id

JOIN customers c
  ON c.id = s.customer_id
 AND c.merchant_id = s.merchant_id

WHERE s.customer_id IS NOT NULL

GROUP BY
    s.merchant_id,
    so.shop_id,
    s.customer_id,
    c.name
;

CREATE UNIQUE INDEX ux_mv_customer_financial_position_by_shop
ON mv_customer_financial_position_by_shop (
    merchant_id,
    shop_id,
    customer_id
);


-- ============================================================
-- SUPPLIER FINANCIAL POSITION BY SHOP
-- Source of truth:
--   purchases.remaining_amount + shop_operations
-- Supplier.debt remains merchant-wide for legacy compatibility.
-- ============================================================

DROP MATERIALIZED VIEW IF EXISTS mv_supplier_financial_position_by_shop CASCADE;

CREATE MATERIALIZED VIEW mv_supplier_financial_position_by_shop AS
SELECT
    p.merchant_id,
    so.shop_id,
    p.supplier_id,
    s.name AS supplier_name,

    COUNT(*) FILTER (
        WHERE p.status <> 'cancelled'
    ) AS purchases_count,

    COALESCE(
        SUM(p.total_amount) FILTER (
            WHERE p.status <> 'cancelled'
        ),
        0
    ) AS total_purchases,

    COALESCE(
        SUM(p.paid_amount) FILTER (
            WHERE p.status <> 'cancelled'
        ),
        0
    ) AS total_paid,

    COALESCE(
        SUM(p.remaining_amount) FILTER (
            WHERE p.status <> 'cancelled'
              AND p.remaining_amount > 0
        ),
        0
    ) AS outstanding_amount,

    COALESCE(
        SUM(p.remaining_amount) FILTER (
            WHERE p.status <> 'cancelled'
              AND p.remaining_amount > 0
              AND p.due_date IS NOT NULL
              AND p.due_date < CURRENT_DATE
        ),
        0
    ) AS overdue_amount,

    MIN(p.due_date) FILTER (
        WHERE p.status <> 'cancelled'
          AND p.remaining_amount > 0
          AND p.due_date IS NOT NULL
    ) AS next_due_date

FROM purchases p

JOIN shop_operations so
  ON so.entity_type = 'purchase'
 AND so.entity_id = p.id
 AND so.merchant_id = p.merchant_id

JOIN suppliers s
  ON s.id = p.supplier_id
 AND s.merchant_id = p.merchant_id

WHERE p.supplier_id IS NOT NULL

GROUP BY
    p.merchant_id,
    so.shop_id,
    p.supplier_id,
    s.name
;

CREATE UNIQUE INDEX ux_mv_supplier_financial_position_by_shop
ON mv_supplier_financial_position_by_shop (
    merchant_id,
    shop_id,
    supplier_id
);
