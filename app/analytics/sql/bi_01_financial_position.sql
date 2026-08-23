
DROP MATERIALIZED VIEW IF EXISTS
mv_customer_financial_position CASCADE;

CREATE MATERIALIZED VIEW mv_customer_financial_position AS
SELECT
    c.merchant_id,
    c.id AS customer_id,
    c.name AS customer_name,

    COUNT(s.id)
        FILTER (WHERE s.status <> 'cancelled')
        AS sales_count,

    COALESCE(
        SUM(s.total_amount)
        FILTER (WHERE s.status <> 'cancelled'),
        0
    ) AS total_sales,

    COALESCE(
        SUM(s.paid_amount)
        FILTER (WHERE s.status <> 'cancelled'),
        0
    ) AS total_paid,

    COALESCE(c.debt, 0) AS outstanding_amount,

    COALESCE(
        SUM(
            CASE
                WHEN s.status <> 'cancelled'
                 AND s.remaining_amount > 0
                 AND s.due_date IS NOT NULL
                 AND s.due_date < CURRENT_DATE
                THEN s.remaining_amount
                ELSE 0
            END
        ),
        0
    ) AS overdue_amount,

    MAX(s.created_at)
        FILTER (WHERE s.status <> 'cancelled')
        AS last_sale_at

FROM customers c

LEFT JOIN sales s
    ON s.customer_id = c.id
   AND s.merchant_id = c.merchant_id

GROUP BY
    c.merchant_id,
    c.id,
    c.name,
    c.debt
;

CREATE UNIQUE INDEX
ux_mv_customer_financial_position
ON mv_customer_financial_position (
    merchant_id,
    customer_id
);


DROP MATERIALIZED VIEW IF EXISTS
mv_supplier_financial_position CASCADE;

CREATE MATERIALIZED VIEW mv_supplier_financial_position AS
SELECT
    s.merchant_id,
    s.id AS supplier_id,
    s.name AS supplier_name,

    COUNT(p.id)
        FILTER (WHERE p.status <> 'cancelled')
        AS purchase_count,

    COALESCE(
        SUM(p.total_amount)
        FILTER (WHERE p.status <> 'cancelled'),
        0
    ) AS total_purchases,

    COALESCE(
        SUM(p.paid_amount)
        FILTER (WHERE p.status <> 'cancelled'),
        0
    ) AS total_paid,

    COALESCE(s.debt, 0) AS outstanding_amount,

    MAX(p.created_at)
        FILTER (WHERE p.status <> 'cancelled')
        AS last_purchase_at

FROM suppliers s

LEFT JOIN purchases p
    ON p.supplier_id = s.id
   AND p.merchant_id = s.merchant_id

GROUP BY
    s.merchant_id,
    s.id,
    s.name,
    s.debt
;

CREATE UNIQUE INDEX
ux_mv_supplier_financial_position
ON mv_supplier_financial_position (
    merchant_id,
    supplier_id
);


DROP MATERIALIZED VIEW IF EXISTS
mv_stock_analytics CASCADE;

CREATE MATERIALIZED VIEW mv_stock_analytics AS
SELECT
    p.merchant_id,
    p.id AS product_id,
    p.name AS product_name,
    p.unit,
    p.stock,
    p.threshold,
    p.purchase_price,
    p.price,

    (
        p.stock
        * COALESCE(p.purchase_price, 0)
    ) AS stock_value,

    (
        p.stock
        * COALESCE(p.price, 0)
    ) AS potential_sales_value,

    (
        p.stock
        * GREATEST(
            COALESCE(p.price, 0)
            - COALESCE(p.purchase_price, 0),
            0
        )
    ) AS potential_gross_margin,

    CASE
        WHEN p.stock <= 0
            THEN 'out_of_stock'
        WHEN p.stock <= p.threshold
            THEN 'low_stock'
        ELSE 'normal'
    END AS stock_status

FROM products p
;

CREATE UNIQUE INDEX
ux_mv_stock_analytics
ON mv_stock_analytics (
    merchant_id,
    product_id
);
