-- Identical durable orchestration schema in Online and isolated Shop simulator.
CREATE TABLE orders (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, order_id uuid NOT NULL,
 source text NOT NULL, request_hash text NOT NULL, lines jsonb NOT NULL,
 device_id text, offline boolean NOT NULL DEFAULT false,
 currency text NOT NULL, total_minor bigint NOT NULL,
 state text NOT NULL, core_state text, core_version integer NOT NULL DEFAULT 0,
 sale_state text, cancel_requested boolean NOT NULL DEFAULT false,
 payment text NOT NULL DEFAULT 'UNPAID', payment_id uuid,
 pending_key uuid, last_error text,
 PRIMARY KEY (tenant_id,shop_id,order_id),
 UNIQUE (tenant_id,shop_id,payment_id)
);
CREATE TABLE outbox (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, idempotency_key uuid NOT NULL,
 order_id uuid NOT NULL, payload jsonb NOT NULL,
 delivered boolean NOT NULL DEFAULT false, attempts integer NOT NULL DEFAULT 0,
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (tenant_id,shop_id,idempotency_key),
 FOREIGN KEY (tenant_id,shop_id,order_id) REFERENCES orders
);
CREATE TABLE inbox (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, event_id uuid NOT NULL,
 fingerprint text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (tenant_id,shop_id,event_id)
);
CREATE TABLE refund_outbox (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, order_id uuid NOT NULL,
 payment_id uuid NOT NULL, amount bigint NOT NULL, currency text NOT NULL,
 delivered boolean NOT NULL DEFAULT false,
 PRIMARY KEY (tenant_id,shop_id,order_id),
 FOREIGN KEY (tenant_id,shop_id,order_id) REFERENCES orders
);
