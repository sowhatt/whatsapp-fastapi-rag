-- Preparatory durable receipts, not a distributed business orchestrator.
SET ROLE j43a_owner;
CREATE TABLE command_receipts (
 merchant_id integer NOT NULL REFERENCES merchants(id),
 source varchar(20) NOT NULL CHECK (source = 'online' OR source = 'shop'),
 idempotency_key uuid NOT NULL,
 command_type varchar(80) NOT NULL,
 payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
 result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (merchant_id, source, idempotency_key)
);
CREATE TABLE inbox_receipts (
 merchant_id integer NOT NULL REFERENCES merchants(id),
 consumer varchar(80) NOT NULL,
 event_id uuid NOT NULL,
 payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
 processed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (merchant_id, consumer, event_id)
);
RESET ROLE;
