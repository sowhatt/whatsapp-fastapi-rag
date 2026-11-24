-- PREPARED ONLY. Never applied during Lot 3.
-- Run the ownership audit below before rollout. No automatic assignment of
-- existing suppliers: ambiguous/multi-shop suppliers require an explicit plan.
-- Existing supplier debt and pilot purchases are not rewritten by this file.
BEGIN;
ALTER TABLE purchases ADD COLUMN initial_paid_amount INTEGER;
-- Legacy initial payments cannot be inferred safely: the new column stays NULL.
ALTER TABLE suppliers ADD COLUMN shop_id INTEGER REFERENCES shops(id);
CREATE INDEX ix_suppliers_shop_id ON suppliers(shop_id);
ALTER TABLE suppliers DROP CONSTRAINT uq_suppliers_merchant_name;
ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_merchant_shop_name UNIQUE (merchant_id, shop_id, name);
CREATE UNIQUE INDEX uq_suppliers_unassigned_name ON suppliers(merchant_id, name) WHERE shop_id IS NULL;
CREATE TABLE purchasing_receipts (
	merchant_id INTEGER NOT NULL, 
	key VARCHAR(36) NOT NULL, 
	shop_id INTEGER NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	response JSON NOT NULL, 
	user_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (merchant_id, key), 
	FOREIGN KEY(merchant_id) REFERENCES merchants (id), 
	FOREIGN KEY(shop_id) REFERENCES shops (id), 
	FOREIGN KEY(user_id) REFERENCES merchant_users (id)
);
CREATE INDEX ix_purchasing_receipts_shop_id ON purchasing_receipts (shop_id);
COMMIT;

-- Read-only ownership audit to prepare a separate reviewed assignment.
-- Unassigned suppliers are intentionally unavailable to shop-scoped endpoints.
-- SELECT s.id, s.merchant_id, s.name, s.debt,
--        COUNT(DISTINCT o.shop_id) AS known_shops,
--        COUNT(p.id) FILTER (WHERE o.shop_id IS NULL) AS unscoped_purchases
-- FROM suppliers s
-- LEFT JOIN purchases p ON p.supplier_id=s.id AND p.merchant_id=s.merchant_id
-- LEFT JOIN shop_operations o ON o.entity_type='purchase' AND o.entity_id=p.id
--                            AND o.merchant_id=s.merchant_id
-- GROUP BY s.id, s.merchant_id, s.name, s.debt;
