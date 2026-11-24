-- Lot 4: diagnostic ONLY, after the two migrations, on a reviewed isolated copy.
-- One SELECT, no mutation. Run in a REPEATABLE READ, READ ONLY transaction.
-- Empty output is necessary, not sufficient: review mapping and provenance too.
WITH scoped AS (
    SELECT p.*, o.shop_id AS operation_shop, o.merchant_id AS operation_merchant,
           sh.merchant_id AS shop_merchant
    FROM purchases p
    LEFT JOIN shop_operations o ON o.entity_type='purchase' AND o.entity_id=p.id
    LEFT JOIN shops sh ON sh.id=o.shop_id
), supplier_summary AS (
    SELECT s.id, s.merchant_id, s.shop_id, s.debt,
           COUNT(DISTINCT p.operation_shop) AS known_shops,
           COALESCE(SUM(p.remaining_amount) FILTER (WHERE p.status<>'cancelled'),0) AS expected_debt
    FROM suppliers s LEFT JOIN scoped p ON p.supplier_id=s.id
    GROUP BY s.id,s.merchant_id,s.shop_id,s.debt
), item_summary AS (
    SELECT purchase_id, SUM(line_total) AS total, SUM(paid_amount) AS paid,
           SUM(remaining_amount) AS remaining
    FROM purchase_items GROUP BY purchase_id
), payment_summary AS (
    SELECT purchase_id, SUM(amount) AS paid FROM supplier_payments GROUP BY purchase_id
), findings AS (
    SELECT 'supplier_unassigned' AS issue, id AS entity_id, merchant_id, shop_id
    FROM suppliers WHERE shop_id IS NULL
    UNION ALL SELECT 'supplier_multiple_shops',id,merchant_id,shop_id
    FROM supplier_summary WHERE known_shops>1
    UNION ALL SELECT 'supplier_debt_mismatch',id,merchant_id,shop_id
    FROM supplier_summary WHERE debt IS DISTINCT FROM expected_debt
    UNION ALL SELECT 'supplier_tenant_mismatch',s.id,s.merchant_id,s.shop_id
    FROM suppliers s LEFT JOIN shops sh ON sh.id=s.shop_id
    WHERE s.merchant_id IS NULL OR (s.shop_id IS NOT NULL AND sh.merchant_id IS DISTINCT FROM s.merchant_id)
    UNION ALL SELECT 'purchase_scope_invalid',id,merchant_id,operation_shop
    FROM scoped WHERE operation_shop IS NULL OR merchant_id IS NULL
       OR operation_merchant IS DISTINCT FROM merchant_id OR shop_merchant IS DISTINCT FROM merchant_id
    UNION ALL SELECT 'purchase_supplier_scope_invalid',p.id,p.merchant_id,p.operation_shop
    FROM scoped p JOIN suppliers s ON s.id=p.supplier_id
    WHERE s.merchant_id IS DISTINCT FROM p.merchant_id
       OR (s.shop_id IS NOT NULL AND s.shop_id IS DISTINCT FROM p.operation_shop)
    UNION ALL SELECT 'purchase_debt_without_supplier',id,merchant_id,operation_shop
    FROM scoped WHERE status<>'cancelled' AND remaining_amount>0 AND supplier_id IS NULL
    UNION ALL SELECT 'purchase_amount_invalid',id,merchant_id,operation_shop
    FROM scoped WHERE total_amount<0 OR paid_amount<0 OR remaining_amount<0
       OR (status<>'cancelled' AND total_amount<>paid_amount+remaining_amount)
    UNION ALL SELECT 'purchase_items_mismatch',p.id,p.merchant_id,p.operation_shop
    FROM scoped p LEFT JOIN item_summary i ON i.purchase_id=p.id
    WHERE p.status<>'cancelled' AND (i.total IS DISTINCT FROM p.total_amount
       OR i.paid IS DISTINCT FROM p.paid_amount OR i.remaining IS DISTINCT FROM p.remaining_amount)
    UNION ALL SELECT 'purchase_payments_mismatch',p.id,p.merchant_id,p.operation_shop
    FROM scoped p LEFT JOIN payment_summary pay ON pay.purchase_id=p.id
    WHERE p.paid_amount IS DISTINCT FROM COALESCE(pay.paid,0)
    UNION ALL SELECT 'payment_scope_invalid',pay.id,pay.merchant_id,p.operation_shop
    FROM supplier_payments pay JOIN scoped p ON p.id=pay.purchase_id
    WHERE pay.merchant_id IS DISTINCT FROM p.merchant_id
       OR pay.supplier_id IS DISTINCT FROM p.supplier_id OR pay.amount<=0 OR pay.paid_at IS NULL
    UNION ALL SELECT 'payment_allocation_mismatch',pay.id,pay.merchant_id,p.operation_shop
    FROM supplier_payments pay JOIN scoped p ON p.id=pay.purchase_id
    LEFT JOIN (SELECT supplier_payment_id,SUM(allocated_amount) AS amount
               FROM supplier_payment_allocations GROUP BY supplier_payment_id) a ON a.supplier_payment_id=pay.id
    WHERE a.amount IS DISTINCT FROM pay.amount
    UNION ALL SELECT 'allocation_scope_invalid',a.id,pay.merchant_id,p.operation_shop
    FROM supplier_payment_allocations a JOIN supplier_payments pay ON pay.id=a.supplier_payment_id
    JOIN purchase_items i ON i.id=a.purchase_item_id JOIN scoped p ON p.id=pay.purchase_id
    WHERE i.purchase_id<>pay.purchase_id OR a.allocated_amount<=0
    UNION ALL SELECT 'inventory_scope_invalid',i.id,i.merchant_id,i.shop_id
    FROM shop_inventories i JOIN shops s ON s.id=i.shop_id JOIN products p ON p.id=i.product_id
    WHERE i.merchant_id IS DISTINCT FROM s.merchant_id OR i.merchant_id IS DISTINCT FROM p.merchant_id
    UNION ALL SELECT 'photo_receipt_scope_invalid',NULL::integer,d.merchant_id,d.shop_id
    FROM sale_photo_drafts d JOIN shops s ON s.id=d.shop_id
    WHERE d.merchant_id IS DISTINCT FROM s.merchant_id
    UNION ALL SELECT 'purchasing_receipt_scope_invalid',NULL::integer,r.merchant_id,r.shop_id
    FROM purchasing_receipts r JOIN shops s ON s.id=r.shop_id
    WHERE r.merchant_id IS DISTINCT FROM s.merchant_id
)
SELECT * FROM findings ORDER BY issue,merchant_id,entity_id;
