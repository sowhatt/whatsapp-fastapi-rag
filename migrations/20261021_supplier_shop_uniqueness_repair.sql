-- Lot 4.1, EXPLICIT repair only for a Lot 3 schema damaged by the old startup.
-- No historical supplier assignment and no monetary UPDATE.
-- Do not run on a pre-Lot3 schema: apply Lot 2/3 first, before starting the app.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('whatzabi_supplier_shop_uniqueness_repair'));
LOCK TABLE suppliers IN ACCESS EXCLUSIVE MODE;
DO $$
DECLARE definition TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_attribute
                   WHERE attrelid='suppliers'::regclass AND attname='shop_id' AND NOT attisdropped) THEN
        RAISE EXCEPTION 'Lot 3 migration required before supplier uniqueness repair';
    END IF;
    SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint
    WHERE conrelid='suppliers'::regclass AND conname='uq_suppliers_merchant_name';
    IF definition IS NOT NULL THEN
        IF definition <> 'UNIQUE (merchant_id, name)' THEN
            RAISE EXCEPTION 'Unexpected legacy supplier constraint: %', definition;
        END IF;
        ALTER TABLE suppliers DROP CONSTRAINT uq_suppliers_merchant_name;
    END IF;
    SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint
    WHERE conrelid='suppliers'::regclass AND conname='uq_suppliers_merchant_shop_name';
    IF definition IS NULL THEN
        ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_merchant_shop_name
            UNIQUE (merchant_id, shop_id, name);
    ELSIF definition <> 'UNIQUE (merchant_id, shop_id, name)' THEN
        RAISE EXCEPTION 'Unexpected shop supplier constraint: %', definition;
    END IF;
    -- Reject unrecognised restrictive indexes; never delete them by guessing.
    IF EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indrelid='suppliers'::regclass AND i.indisunique AND i.indpred IS NULL
          AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
               FROM unnest(i.indkey::smallint[]) k
               JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k)
              IN (ARRAY['name'], ARRAY['merchant_id','name'])
    ) THEN
        RAISE EXCEPTION 'Unexpected restrictive supplier index; explicit review required';
    END IF;
    -- The Lot3 partial index must already exist and have the expected definition.
    IF NOT EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indrelid='suppliers'::regclass AND i.indisunique AND i.indisvalid
          AND pg_get_expr(i.indpred,i.indrelid) = '(shop_id IS NULL)'
          AND (SELECT array_agg(a.attname::text ORDER BY k.ordinality)
               FROM unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum,ordinality)
               JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum)
              = ARRAY['merchant_id','name']
    ) THEN
        RAISE EXCEPTION 'Missing or invalid Lot3 unassigned supplier index; explicit review required';
    END IF;
END $$;
COMMIT;
