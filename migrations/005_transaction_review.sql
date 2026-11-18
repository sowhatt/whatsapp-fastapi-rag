-- Read-only diagnostic. Review the provenance of legacy opening debt separately.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
-- Every confirmed payment must be fully allocated to items of its own purchase.
SELECT p.id, p.purchase_id, p.amount, coalesce(sum(a.allocated_amount),0) AS allocated,
       count(*) FILTER (WHERE i.purchase_id <> p.purchase_id) AS foreign_items
FROM supplier_payments p
LEFT JOIN supplier_payment_allocations a ON a.supplier_payment_id=p.id
LEFT JOIN purchase_items i ON i.id=a.purchase_item_id
GROUP BY p.id HAVING p.amount <> coalesce(sum(a.allocated_amount),0)
    OR count(*) FILTER (WHERE i.purchase_id <> p.purchase_id)>0;
-- Active purchase aggregate vs immutable payments and current item balances.
SELECT p.id, p.merchant_id, p.total_amount, p.paid_amount, p.remaining_amount
FROM purchases p WHERE p.status <> 'cancelled' AND (
    p.total_amount <> p.paid_amount+p.remaining_amount OR p.remaining_amount<0 OR p.paid_amount<0
    OR p.total_amount <> (SELECT coalesce(sum(i.line_total),0) FROM purchase_items i WHERE i.purchase_id=p.id)
    OR p.paid_amount <> (SELECT coalesce(sum(s.amount),0) FROM supplier_payments s WHERE s.purchase_id=p.id)
    OR p.paid_amount <> (SELECT coalesce(sum(i.paid_amount),0) FROM purchase_items i WHERE i.purchase_id=p.id)
    OR p.remaining_amount <> (SELECT coalesce(sum(i.remaining_amount),0) FROM purchase_items i WHERE i.purchase_id=p.id));
-- Differences may include opening debt: report, do not rewrite.
SELECT s.id, s.merchant_id, s.debt,
       coalesce(sum(p.remaining_amount) FILTER (WHERE p.status <> 'cancelled'),0) AS purchase_debt
FROM suppliers s LEFT JOIN purchases p ON p.supplier_id=s.id
GROUP BY s.id HAVING s.debt <> coalesce(sum(p.remaining_amount) FILTER (WHERE p.status <> 'cancelled'),0);
-- Every committed idempotency record must have a receipt.
SELECT id, merchant_id, shop_scope, operation FROM purchase_requests WHERE receipt IS NULL;
ROLLBACK;
