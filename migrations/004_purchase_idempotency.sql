-- Explicit migration only, during a write maintenance window. No historical rewrite.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SELECT pg_advisory_xact_lock(20261030, 4);
CREATE TABLE IF NOT EXISTS public.purchase_requests (
    id SERIAL PRIMARY KEY,
    merchant_id INTEGER NOT NULL REFERENCES public.merchants(id),
    shop_scope INTEGER NOT NULL,
    operation VARCHAR(30) NOT NULL,
    request_key VARCHAR(128) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    receipt JSON NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    CONSTRAINT uq_purchase_request_scope_key UNIQUE (merchant_id, shop_scope, operation, request_key),
    CONSTRAINT ck_purchase_request_scope CHECK (shop_scope >= 0)
);
COMMIT;
