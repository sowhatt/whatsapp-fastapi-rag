-- Legacy co-located schema only; authorised tenant context required.
-- Counts are not globally exhaustive when RLS hides other tenants.
-- No repair, payment capture, stock decrement, or event publication.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='10s';
SELECT count(*) AS divergent_core_status
FROM online_orders o JOIN business_transactions t ON t.id=o.transaction_id
WHERE o.merchant_id=t.merchant_id AND t.status <>
 CASE WHEN o.status IN ('preparing','ready') THEN 'confirmed' ELSE o.status END;
SELECT count(*) AS cross_tenant_or_missing_core_root
FROM online_orders o LEFT JOIN business_transactions t ON t.id=o.transaction_id
WHERE t.id IS NULL OR t.merchant_id<>o.merchant_id;
SELECT count(*) AS payment_or_total_mismatch
FROM online_orders o JOIN business_transactions t ON t.id=o.transaction_id AND t.merchant_id=o.merchant_id
WHERE o.currency<>t.currency OR o.total_amount<>t.total_amount OR o.payment_status<>t.payment_status;
SELECT count(*) AS active_expired_reservations FROM stock_reservations
WHERE status='active' AND expires_at<=CURRENT_TIMESTAMP AT TIME ZONE 'UTC';
SELECT count(*) AS ownerless_products FROM products WHERE merchant_id IS NULL;
SELECT count(*) AS invalid_quantities FROM stock_reservations WHERE quantity<=0;
SELECT count(*) AS foreign_product_reservations FROM stock_reservations r
JOIN products p ON p.id=r.product_id WHERE r.merchant_id IS DISTINCT FROM p.merchant_id;
SELECT status,event_type,count(*) FROM outbox_events GROUP BY status,event_type ORDER BY 1,2;
COMMIT;
