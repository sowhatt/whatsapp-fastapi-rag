-- LAB ONLY: tenant-consistent references while domains remain co-located.
SET ROLE j43a_owner;
ALTER TABLE payment_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_allocations FORCE ROW LEVEL SECURITY;
-- No policy and no grants: fail closed for legacy child tables.
ALTER TABLE purchase_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_items FORCE ROW LEVEL SECURITY;
-- No policy and no grants: fail closed for legacy child tables.
ALTER TABLE sale_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE sale_items FORCE ROW LEVEL SECURITY;
-- No policy and no grants: fail closed for legacy child tables.
ALTER TABLE supplier_payment_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier_payment_allocations FORCE ROW LEVEL SECURITY;
-- No policy and no grants: fail closed for legacy child tables.
ALTER TABLE business_transactions ADD CONSTRAINT uq_tenant_business_transactions UNIQUE (merchant_id,id);
ALTER TABLE categories ADD CONSTRAINT uq_tenant_categories UNIQUE (merchant_id,id);
ALTER TABLE online_carts ADD CONSTRAINT uq_tenant_online_carts UNIQUE (merchant_id,id);
ALTER TABLE online_orders ADD CONSTRAINT uq_tenant_online_orders UNIQUE (merchant_id,id);
ALTER TABLE online_stores ADD CONSTRAINT uq_tenant_online_stores UNIQUE (merchant_id,id);
ALTER TABLE products ADD CONSTRAINT uq_tenant_products UNIQUE (merchant_id,id);
ALTER TABLE online_cart_items ADD CONSTRAINT fk_tenant_online_cart_items_cart_id FOREIGN KEY (merchant_id,cart_id) REFERENCES online_carts(merchant_id,id);
ALTER TABLE online_cart_items ADD CONSTRAINT fk_tenant_online_cart_items_product_id FOREIGN KEY (merchant_id,product_id) REFERENCES products(merchant_id,id);
ALTER TABLE online_carts ADD CONSTRAINT fk_tenant_online_carts_store_id FOREIGN KEY (merchant_id,store_id) REFERENCES online_stores(merchant_id,id);
ALTER TABLE online_order_items ADD CONSTRAINT fk_tenant_online_order_items_order_id FOREIGN KEY (merchant_id,order_id) REFERENCES online_orders(merchant_id,id);
ALTER TABLE online_order_items ADD CONSTRAINT fk_tenant_online_order_items_product_id FOREIGN KEY (merchant_id,product_id) REFERENCES products(merchant_id,id);
ALTER TABLE online_orders ADD CONSTRAINT fk_tenant_online_orders_cart_id FOREIGN KEY (merchant_id,cart_id) REFERENCES online_carts(merchant_id,id);
ALTER TABLE online_orders ADD CONSTRAINT fk_tenant_online_orders_store_id FOREIGN KEY (merchant_id,store_id) REFERENCES online_stores(merchant_id,id);
ALTER TABLE online_orders ADD CONSTRAINT fk_tenant_online_orders_transaction_id FOREIGN KEY (merchant_id,transaction_id) REFERENCES business_transactions(merchant_id,id);
ALTER TABLE online_product_images ADD CONSTRAINT fk_tenant_online_product_images_product_id FOREIGN KEY (merchant_id,product_id) REFERENCES products(merchant_id,id);
ALTER TABLE online_product_publications ADD CONSTRAINT fk_tenant_online_product_publications_product_id FOREIGN KEY (merchant_id,product_id) REFERENCES products(merchant_id,id);
ALTER TABLE products ADD CONSTRAINT fk_tenant_products_category_id FOREIGN KEY (merchant_id,category_id) REFERENCES categories(merchant_id,id);
ALTER TABLE stock_movements ADD CONSTRAINT fk_tenant_stock_movements_product_id FOREIGN KEY (merchant_id,product_id) REFERENCES products(merchant_id,id);
ALTER TABLE stock_reservations ADD CONSTRAINT fk_tenant_stock_reservations_product_id FOREIGN KEY (merchant_id,product_id) REFERENCES products(merchant_id,id);
ALTER TABLE online_cart_items ADD CONSTRAINT ck_positive_online_cart_items CHECK (quantity > 0);
ALTER TABLE online_order_items ADD CONSTRAINT ck_positive_online_order_items CHECK (quantity > 0);
ALTER TABLE stock_reservations ADD CONSTRAINT ck_positive_stock_reservations CHECK (quantity > 0);
RESET ROLE;
