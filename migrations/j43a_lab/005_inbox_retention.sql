-- LAB ONLY: append-only deduplication receipts and separate tenant-scoped purge.
-- 90 days is a minimum lab retention, not an approved production replay window.
SET ROLE j43a_owner;
REVOKE UPDATE, DELETE, INSERT ON inbox_receipts FROM j43a_online_runtime, j43a_worker;
GRANT INSERT (merchant_id, consumer, event_id, payload_hash)
    ON inbox_receipts TO j43a_online_runtime, j43a_worker;
-- No runtime can backdate a receipt, including from a long-running transaction.
ALTER TABLE inbox_receipts ALTER COLUMN processed_at SET DEFAULT clock_timestamp();
GRANT SELECT, DELETE ON inbox_receipts TO j43a_inbox_maintenance;
-- Restrictive: AND with tenant_isolation, never an alternative tenant grant.
CREATE POLICY inbox_retention ON inbox_receipts AS RESTRICTIVE
    FOR DELETE TO PUBLIC
    USING (current_user = 'j43a_inbox_maintenance'
           AND processed_at < statement_timestamp() - interval '2160 hours');
RESET ROLE;
