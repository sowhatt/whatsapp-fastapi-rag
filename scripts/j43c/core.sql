-- Empty, disposable Core database only. No cross-database foreign keys.
CREATE TABLE inventory (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, product_id bigint NOT NULL,
 physical integer NOT NULL CHECK (physical >= 0),
 reserved integer NOT NULL DEFAULT 0 CHECK (reserved >= 0 AND reserved <= physical),
 consumed integer NOT NULL DEFAULT 0 CHECK (consumed >= 0),
 version integer NOT NULL DEFAULT 0,
 PRIMARY KEY (tenant_id,shop_id,product_id)
);
CREATE TABLE reservations (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, source text NOT NULL,
 order_id uuid NOT NULL, device_id text,
 lines jsonb NOT NULL, state text NOT NULL CHECK (state IN ('ACTIVE','CONFIRMED','CONSUMED','RELEASED','EXPIRED','CANCELLED')),
 version integer NOT NULL, expires_at timestamptz,
 sale_state text CHECK (sale_state IN ('PENDING','RECORDED','CANCELLED')),
 currency text, total_minor bigint,
 PRIMARY KEY (tenant_id,shop_id,source,order_id)
);
CREATE TABLE movements (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, source text NOT NULL,
 order_id uuid NOT NULL, product_id bigint NOT NULL, kind text NOT NULL,
 delta integer NOT NULL,
 PRIMARY KEY (tenant_id,shop_id,source,order_id,product_id,kind),
 FOREIGN KEY (tenant_id,shop_id,source,order_id) REFERENCES reservations,
 FOREIGN KEY (tenant_id,shop_id,product_id) REFERENCES inventory
);
CREATE TABLE receipts (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, source text NOT NULL,
 idempotency_key uuid NOT NULL, fingerprint text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (tenant_id,shop_id,source,idempotency_key)
);
CREATE TABLE outbox (
 tenant_id bigint NOT NULL, shop_id bigint NOT NULL, event_id uuid NOT NULL,
 payload jsonb NOT NULL, delivered boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (tenant_id,shop_id,event_id)
);
GRANT SELECT, INSERT, UPDATE ON inventory, reservations TO j43c_core_runtime;
GRANT SELECT, INSERT ON movements, receipts, outbox TO j43c_core_runtime;
GRANT SELECT ON outbox TO j43c_core_worker;
GRANT UPDATE (delivered) ON outbox TO j43c_core_worker;
