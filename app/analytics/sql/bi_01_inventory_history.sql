
-- ============================================================
-- BI-01.4 V2
-- INVENTORY DAILY HISTORY
-- ============================================================

CREATE TABLE IF NOT EXISTS fact_inventory_daily_snapshot (
    id BIGSERIAL PRIMARY KEY,

    snapshot_date DATE NOT NULL,
    merchant_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,

    product_name TEXT NOT NULL,
    unit TEXT,

    stock_quantity NUMERIC NOT NULL DEFAULT 0,
    unit_cost NUMERIC NOT NULL DEFAULT 0,
    stock_value NUMERIC NOT NULL DEFAULT 0,

    potential_sales_value NUMERIC NOT NULL DEFAULT 0,

    quantity_sold_day NUMERIC NOT NULL DEFAULT 0,
    sales_revenue_day NUMERIC NOT NULL DEFAULT 0,
    cogs_day NUMERIC NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_inventory_snapshot_day
        UNIQUE (snapshot_date, merchant_id, product_id)
);

CREATE INDEX IF NOT EXISTS
    ix_inventory_snapshot_merchant_date
ON fact_inventory_daily_snapshot (
    merchant_id,
    snapshot_date DESC
);

CREATE INDEX IF NOT EXISTS
    ix_inventory_snapshot_product_date
ON fact_inventory_daily_snapshot (
    merchant_id,
    product_id,
    snapshot_date DESC
);
