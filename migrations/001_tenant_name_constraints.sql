-- Explicit migration only, outside the API, during a maintenance window.
-- Repairs only the three known legacy global-name uniqueness constraints.
-- No data correction, no composite-constraint drop, no arbitrary LIMIT 1.
-- If dependencies or duplicate rows prevent this operation, ROLLBACK and review.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path TO public, pg_catalog;
LOCK TABLE public.products, public.categories, public.suppliers IN ACCESS EXCLUSIVE MODE;
DO $$
DECLARE
    table_name text;
    table_oid oid;
    name_att smallint;
    merchant_att smallint;
    item record;
    duplicate_found boolean;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['products', 'categories', 'suppliers'] LOOP
        table_oid := ('public.' || table_name)::regclass;
        SELECT attnum INTO STRICT name_att FROM pg_attribute
          WHERE attrelid = table_oid AND attname = 'name' AND NOT attisdropped;
        SELECT attnum INTO STRICT merchant_att FROM pg_attribute
          WHERE attrelid = table_oid AND attname = 'merchant_id' AND NOT attisdropped;
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I WHERE merchant_id IS NOT NULL GROUP BY merchant_id, name HAVING count(*) > 1)', table_name)
          INTO duplicate_found;
        IF duplicate_found THEN
            RAISE EXCEPTION 'Duplicate merchant/name rows in %, manual review required', table_name;
        END IF;
        FOR item IN SELECT conname FROM pg_constraint
          WHERE conrelid = table_oid AND contype = 'u' AND conkey = ARRAY[name_att]
        LOOP
            EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', table_name, item.conname);
        END LOOP;
        FOR item IN SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
          WHERE i.indrelid = table_oid AND i.indisunique AND i.indnkeyatts = 1
            AND i.indkey[0] = name_att AND i.indpred IS NULL AND i.indexprs IS NULL
            AND NOT EXISTS (SELECT 1 FROM pg_constraint x WHERE x.conindid = i.indexrelid)
        LOOP
            EXECUTE format('DROP INDEX public.%I', item.relname);
        END LOOP;
        IF NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = table_oid
            AND i.indisunique AND i.indisvalid AND i.indisready AND i.indnkeyatts = 2
            AND i.indkey[0] = merchant_att AND i.indkey[1] = name_att
            AND i.indpred IS NULL AND i.indexprs IS NULL) THEN
            EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I UNIQUE (merchant_id, name)',
              table_name, 'uq_' || table_name || '_merchant_name');
        END IF;
    END LOOP;
END $$;
COMMIT;
