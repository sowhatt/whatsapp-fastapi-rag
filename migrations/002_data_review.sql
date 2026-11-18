-- Diagnostic only. No decision about ownership or historical cost is inferred.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path TO public, pg_catalog;
SELECT 'customers' AS relation, count(*) AS unassigned FROM customers WHERE merchant_id IS NULL
UNION ALL SELECT 'suppliers', count(*) FROM suppliers WHERE merchant_id IS NULL
UNION ALL SELECT 'products', count(*) FROM products WHERE merchant_id IS NULL
UNION ALL SELECT 'categories', count(*) FROM categories WHERE merchant_id IS NULL
UNION ALL SELECT 'sales', count(*) FROM sales WHERE merchant_id IS NULL
UNION ALL SELECT 'purchases', count(*) FROM purchases WHERE merchant_id IS NULL
UNION ALL SELECT 'financial_entries', count(*) FROM financial_entries WHERE merchant_id IS NULL
UNION ALL SELECT 'payments', count(*) FROM payments WHERE merchant_id IS NULL
UNION ALL SELECT 'supplier_payments', count(*) FROM supplier_payments WHERE merchant_id IS NULL
UNION ALL SELECT 'stock_movements', count(*) FROM stock_movements WHERE merchant_id IS NULL
UNION ALL SELECT 'transaction_events', count(*) FROM transaction_events WHERE merchant_id IS NULL;
-- Zero is a legitimate historical value; current purchase_price is NOT evidence.
SELECT count(*) AS historical_zero_costs_to_review FROM sale_items WHERE unit_cost_snapshot = 0;
SELECT id AS sale_id, merchant_id, sale_number FROM sales WHERE sale_number IS NULL ORDER BY id;
SELECT merchant_id, max(sale_number) AS last_number FROM sales GROUP BY merchant_id ORDER BY merchant_id;
SELECT merchant_id, sale_number, count(*) FROM sales WHERE sale_number IS NOT NULL AND merchant_id IS NOT NULL GROUP BY merchant_id, sale_number HAVING count(*) > 1;
SELECT merchant_id, name, count(*) FROM suppliers WHERE merchant_id IS NOT NULL GROUP BY merchant_id, name HAVING count(*) > 1;
SELECT id AS merchant_id FROM merchants WHERE subscription_status IS NULL;
SELECT code, name, symbol, decimals, is_active FROM currencies ORDER BY code;
ROLLBACK;
