-- LAB ONLY: frozen ORM baseline from e34ea2f; never run on an existing/remote database.
SET ROLE j43a_owner;
CREATE TABLE currencies (
	id SERIAL NOT NULL,
	code VARCHAR(3) NOT NULL,
	name VARCHAR(100) NOT NULL,
	symbol VARCHAR(20),
	decimals INTEGER NOT NULL,
	is_active BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_currencies_code ON currencies (code);
CREATE INDEX ix_currencies_id ON currencies (id);
CREATE TABLE merchants (
	id SERIAL NOT NULL,
	whatsapp_number VARCHAR(30) NOT NULL,
	shop_name VARCHAR(150),
	subscription_status VARCHAR(20) DEFAULT 'pilot' NOT NULL,
	subscription_ends_at TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
);
CREATE INDEX ix_merchants_id ON merchants (id);
CREATE INDEX ix_merchants_subscription_status ON merchants (subscription_status);
CREATE UNIQUE INDEX ix_merchants_whatsapp_number ON merchants (whatsapp_number);
CREATE TABLE online_notifications (
	id SERIAL NOT NULL,
	source_event_id VARCHAR(36) NOT NULL,
	merchant_id INTEGER NOT NULL,
	aggregate_type VARCHAR(80) NOT NULL,
	aggregate_id VARCHAR(100) NOT NULL,
	recipient_role VARCHAR(30) NOT NULL,
	channel VARCHAR(30) NOT NULL,
	title VARCHAR(180) NOT NULL,
	body TEXT NOT NULL,
	action_url VARCHAR(2000),
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	read_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (source_event_id)
);
CREATE INDEX ix_online_notifications_id ON online_notifications (id);
CREATE INDEX ix_online_notifications_merchant_id ON online_notifications (merchant_id);
CREATE INDEX ix_online_notifications_merchant_status_created_at ON online_notifications (merchant_id, status, created_at);
CREATE TABLE outbox_events (
	id SERIAL NOT NULL,
	event_id VARCHAR(36) NOT NULL,
	merchant_id INTEGER NOT NULL,
	aggregate_type VARCHAR(80) NOT NULL,
	aggregate_id VARCHAR(100) NOT NULL,
	event_type VARCHAR(120) NOT NULL,
	event_version INTEGER NOT NULL,
	payload JSON NOT NULL,
	status VARCHAR(20) NOT NULL,
	retry_count INTEGER NOT NULL,
	last_error TEXT,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	published_at TIMESTAMP WITHOUT TIME ZONE,
	next_attempt_at TIMESTAMP WITHOUT TIME ZONE,
	processing_started_at TIMESTAMP WITHOUT TIME ZONE,
	provider_message_id VARCHAR(255),
	PRIMARY KEY (id),
	UNIQUE (event_id)
);
CREATE INDEX ix_outbox_events_id ON outbox_events (id);
CREATE INDEX ix_outbox_events_merchant_created_at ON outbox_events (merchant_id, created_at);
CREATE INDEX ix_outbox_events_merchant_id ON outbox_events (merchant_id);
CREATE INDEX ix_outbox_events_status_created_at ON outbox_events (status, created_at);
CREATE INDEX ix_outbox_events_status_next_attempt_at ON outbox_events (status, next_attempt_at);
CREATE TABLE web_push_subscriptions (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	endpoint TEXT NOT NULL,
	p256dh VARCHAR(255) NOT NULL,
	auth VARCHAR(255) NOT NULL,
	is_active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (endpoint)
);
CREATE INDEX ix_web_push_subscriptions_id ON web_push_subscriptions (id);
CREATE INDEX ix_web_push_subscriptions_merchant_active ON web_push_subscriptions (merchant_id, is_active);
CREATE INDEX ix_web_push_subscriptions_merchant_id ON web_push_subscriptions (merchant_id);
CREATE TABLE business_transactions (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	shop_id INTEGER,
	kind VARCHAR(30) NOT NULL,
	status VARCHAR(30) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	subtotal_amount INTEGER NOT NULL,
	tax_amount INTEGER NOT NULL,
	fee_amount INTEGER NOT NULL,
	discount_amount INTEGER NOT NULL,
	total_amount INTEGER NOT NULL,
	payment_status VARCHAR(30) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_business_transactions_id ON business_transactions (id);
CREATE INDEX ix_business_transactions_merchant_created_at ON business_transactions (merchant_id, created_at);
CREATE INDEX ix_business_transactions_merchant_id ON business_transactions (merchant_id);
CREATE INDEX ix_business_transactions_merchant_kind_status ON business_transactions (merchant_id, kind, status);
CREATE INDEX ix_business_transactions_shop_id ON business_transactions (shop_id);
CREATE TABLE categories (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	name VARCHAR(100) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_categories_merchant_name UNIQUE (merchant_id, name),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_categories_id ON categories (id);
CREATE INDEX ix_categories_merchant_id ON categories (merchant_id);
CREATE INDEX ix_categories_name ON categories (name);
CREATE TABLE customers (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	name VARCHAR(100) NOT NULL,
	phone VARCHAR(30),
	debt INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_customers_id ON customers (id);
CREATE INDEX ix_customers_merchant_id ON customers (merchant_id);
CREATE INDEX ix_customers_name ON customers (name);
CREATE TABLE exchange_rates (
	id SERIAL NOT NULL,
	base_currency_id INTEGER NOT NULL,
	quote_currency_id INTEGER NOT NULL,
	rate NUMERIC(20, 8) NOT NULL,
	source VARCHAR(100) NOT NULL,
	retrieved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	valid_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(base_currency_id) REFERENCES currencies (id),
	FOREIGN KEY(quote_currency_id) REFERENCES currencies (id)
);
CREATE INDEX ix_exchange_rates_base_currency_id ON exchange_rates (base_currency_id);
CREATE INDEX ix_exchange_rates_id ON exchange_rates (id);
CREATE INDEX ix_exchange_rates_quote_currency_id ON exchange_rates (quote_currency_id);
CREATE TABLE financial_entries (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	entry_type VARCHAR(20) NOT NULL,
	amount INTEGER NOT NULL,
	channel VARCHAR(30) NOT NULL,
	label VARCHAR(100) NOT NULL,
	category VARCHAR(30),
	note VARCHAR(255),
	origin_kind VARCHAR(20) NOT NULL,
	reference_type VARCHAR(50),
	reference_id INTEGER,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_financial_entries_id ON financial_entries (id);
CREATE INDEX ix_financial_entries_merchant_id ON financial_entries (merchant_id);
CREATE TABLE online_stores (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	slug VARCHAR(80) NOT NULL,
	display_name VARCHAR(150) NOT NULL,
	description VARCHAR(500),
	logo_url VARCHAR(1000),
	banner_url VARCHAR(1000),
	primary_color VARCHAR(20),
	accent_color VARCHAR(20),
	business_type VARCHAR(30) NOT NULL,
	capabilities_json TEXT,
	template VARCHAR(30) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	country_code VARCHAR(2) NOT NULL,
	seo_title VARCHAR(180),
	seo_description VARCHAR(320),
	canonical_domain VARCHAR(255),
	address VARCHAR(300),
	city VARCHAR(120),
	postal_code VARCHAR(30),
	latitude VARCHAR(40),
	longitude VARCHAR(40),
	is_active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_online_stores_id ON online_stores (id);
CREATE UNIQUE INDEX ix_online_stores_merchant_id ON online_stores (merchant_id);
CREATE UNIQUE INDEX ix_online_stores_slug ON online_stores (slug);
CREATE TABLE open_tabs (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	table_name VARCHAR(50) NOT NULL,
	status VARCHAR(20) DEFAULT 'open' NOT NULL,
	total_amount INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	closed_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_open_tabs_id ON open_tabs (id);
CREATE INDEX ix_open_tabs_merchant_id ON open_tabs (merchant_id);
CREATE INDEX ix_open_tabs_table_name ON open_tabs (table_name);
CREATE TABLE suppliers (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	name VARCHAR(100) NOT NULL,
	phone VARCHAR(30),
	debt INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_suppliers_merchant_name UNIQUE (merchant_id, name),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_suppliers_id ON suppliers (id);
CREATE INDEX ix_suppliers_merchant_id ON suppliers (merchant_id);
CREATE INDEX ix_suppliers_name ON suppliers (name);
CREATE TABLE transaction_events (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	entity_type VARCHAR(50) NOT NULL,
	entity_id INTEGER NOT NULL,
	event_type VARCHAR(50) NOT NULL,
	amount_signed INTEGER,
	note VARCHAR(255),
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_transaction_events_id ON transaction_events (id);
CREATE INDEX ix_transaction_events_merchant_id ON transaction_events (merchant_id);
CREATE TABLE online_carts (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	store_id INTEGER NOT NULL,
	token VARCHAR(36) NOT NULL,
	status VARCHAR(20) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(store_id) REFERENCES online_stores (id)
);
CREATE INDEX ix_online_carts_id ON online_carts (id);
CREATE INDEX ix_online_carts_merchant_id ON online_carts (merchant_id);
CREATE INDEX ix_online_carts_merchant_status ON online_carts (merchant_id, status);
CREATE INDEX ix_online_carts_store_id ON online_carts (store_id);
CREATE UNIQUE INDEX ix_online_carts_token ON online_carts (token);
CREATE TABLE products (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	category_id INTEGER,
	name VARCHAR(100) NOT NULL,
	product_type VARCHAR(100),
	brand VARCHAR(100),
	variant VARCHAR(100),
	packaging VARCHAR(100),
	unit VARCHAR(30) NOT NULL,
	stock INTEGER NOT NULL,
	initial_stock INTEGER NOT NULL,
	purchase_price INTEGER NOT NULL,
	price INTEGER NOT NULL,
	threshold INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_products_merchant_name UNIQUE (merchant_id, name),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(category_id) REFERENCES categories (id)
);
CREATE INDEX ix_products_category_id ON products (category_id);
CREATE INDEX ix_products_id ON products (id);
CREATE INDEX ix_products_merchant_id ON products (merchant_id);
CREATE INDEX ix_products_name ON products (name);
CREATE INDEX ix_products_product_type ON products (product_type);
CREATE TABLE purchases (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	supplier_id INTEGER,
	total_amount INTEGER NOT NULL,
	paid_amount INTEGER NOT NULL,
	remaining_amount INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	due_date DATE,
	original_amount INTEGER,
	original_currency VARCHAR(3) NOT NULL,
	exchange_rate NUMERIC(20, 8),
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	cancelled_at TIMESTAMP WITHOUT TIME ZONE,
	cancellation_reason VARCHAR(255),
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id)
);
CREATE INDEX ix_purchases_id ON purchases (id);
CREATE INDEX ix_purchases_merchant_id ON purchases (merchant_id);
CREATE TABLE sales (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	sale_number INTEGER,
	customer_id INTEGER,
	total_amount INTEGER NOT NULL,
	paid_amount INTEGER NOT NULL,
	remaining_amount INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	due_date DATE,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_sales_merchant_sale_number UNIQUE (merchant_id, sale_number),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);
CREATE INDEX ix_sales_id ON sales (id);
CREATE INDEX ix_sales_merchant_id ON sales (merchant_id);
CREATE TABLE online_cart_items (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	cart_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	unit_price_snapshot INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_online_cart_item_cart_product UNIQUE (cart_id, product_id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(cart_id) REFERENCES online_carts (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_online_cart_items_cart_id ON online_cart_items (cart_id);
CREATE INDEX ix_online_cart_items_id ON online_cart_items (id);
CREATE INDEX ix_online_cart_items_merchant_id ON online_cart_items (merchant_id);
CREATE INDEX ix_online_cart_items_product_id ON online_cart_items (product_id);
CREATE TABLE online_orders (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	store_id INTEGER NOT NULL,
	transaction_id INTEGER NOT NULL,
	cart_id INTEGER NOT NULL,
	reference VARCHAR(20) NOT NULL,
	status VARCHAR(30) NOT NULL,
	customer_name VARCHAR(150) NOT NULL,
	customer_phone VARCHAR(40) NOT NULL,
	delivery_mode VARCHAR(20) NOT NULL,
	delivery_address VARCHAR(500),
	notes VARCHAR(500),
	currency VARCHAR(3) NOT NULL,
	subtotal_amount INTEGER NOT NULL,
	delivery_amount INTEGER NOT NULL,
	total_amount INTEGER NOT NULL,
	payment_method VARCHAR(30) NOT NULL,
	payment_status VARCHAR(30) NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(store_id) REFERENCES online_stores (id),
	FOREIGN KEY(transaction_id) REFERENCES business_transactions (id),
	UNIQUE (cart_id),
	FOREIGN KEY(cart_id) REFERENCES online_carts (id)
);
CREATE INDEX ix_online_orders_id ON online_orders (id);
CREATE INDEX ix_online_orders_merchant_id ON online_orders (merchant_id);
CREATE INDEX ix_online_orders_merchant_status ON online_orders (merchant_id, status);
CREATE UNIQUE INDEX ix_online_orders_reference ON online_orders (reference);
CREATE INDEX ix_online_orders_store_created_at ON online_orders (store_id, created_at);
CREATE INDEX ix_online_orders_store_id ON online_orders (store_id);
CREATE UNIQUE INDEX ix_online_orders_transaction_id ON online_orders (transaction_id);
CREATE TABLE online_product_images (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	image_url VARCHAR(1000) NOT NULL,
	storage_key VARCHAR(500),
	is_primary BOOLEAN NOT NULL,
	position INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_online_product_images_id ON online_product_images (id);
CREATE INDEX ix_online_product_images_merchant_id ON online_product_images (merchant_id);
CREATE INDEX ix_online_product_images_product_id ON online_product_images (product_id);
CREATE TABLE online_product_publications (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	is_published BOOLEAN NOT NULL,
	is_active BOOLEAN NOT NULL,
	show_price BOOLEAN NOT NULL,
	show_stock BOOLEAN NOT NULL,
	description VARCHAR(500),
	seo_slug VARCHAR(120),
	seo_title VARCHAR(180),
	seo_description VARCHAR(320),
	display_order INTEGER NOT NULL,
	published_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_online_product_publication_merchant_product UNIQUE (merchant_id, product_id),
	CONSTRAINT uq_online_product_publication_merchant_seo_slug UNIQUE (merchant_id, seo_slug),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_online_product_publications_id ON online_product_publications (id);
CREATE INDEX ix_online_product_publications_merchant_id ON online_product_publications (merchant_id);
CREATE INDEX ix_online_product_publications_product_id ON online_product_publications (product_id);
CREATE INDEX ix_online_product_publications_seo_slug ON online_product_publications (seo_slug);
CREATE TABLE open_tab_items (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	tab_id INTEGER NOT NULL,
	product_id INTEGER,
	product_name VARCHAR(100) NOT NULL,
	unit VARCHAR(30) NOT NULL,
	quantity INTEGER NOT NULL,
	unit_price INTEGER NOT NULL,
	line_total INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(tab_id) REFERENCES open_tabs (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_open_tab_items_id ON open_tab_items (id);
CREATE INDEX ix_open_tab_items_merchant_id ON open_tab_items (merchant_id);
CREATE INDEX ix_open_tab_items_tab_id ON open_tab_items (tab_id);
CREATE TABLE payments (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	sale_id INTEGER NOT NULL,
	customer_id INTEGER,
	amount INTEGER NOT NULL,
	channel VARCHAR(30) NOT NULL,
	reference VARCHAR(100),
	paid_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(sale_id) REFERENCES sales (id),
	FOREIGN KEY(customer_id) REFERENCES customers (id)
);
CREATE INDEX ix_payments_id ON payments (id);
CREATE INDEX ix_payments_merchant_id ON payments (merchant_id);
CREATE TABLE product_images (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	image_url VARCHAR(1000) NOT NULL,
	storage_key VARCHAR(500),
	is_primary BOOLEAN NOT NULL,
	position INTEGER NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_product_images_id ON product_images (id);
CREATE INDEX ix_product_images_merchant_id ON product_images (merchant_id);
CREATE INDEX ix_product_images_product_id ON product_images (product_id);
CREATE TABLE product_publications (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	is_published BOOLEAN NOT NULL,
	is_active BOOLEAN NOT NULL,
	show_price BOOLEAN NOT NULL,
	show_stock BOOLEAN NOT NULL,
	description VARCHAR(500),
	display_order INTEGER NOT NULL,
	published_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_product_publication_merchant_product UNIQUE (merchant_id, product_id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_product_publications_id ON product_publications (id);
CREATE INDEX ix_product_publications_merchant_id ON product_publications (merchant_id);
CREATE INDEX ix_product_publications_product_id ON product_publications (product_id);
CREATE TABLE purchase_items (
	id SERIAL NOT NULL,
	purchase_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	unit_cost INTEGER NOT NULL,
	line_total INTEGER NOT NULL,
	paid_amount INTEGER NOT NULL,
	remaining_amount INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(purchase_id) REFERENCES purchases (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_purchase_items_id ON purchase_items (id);
CREATE TABLE sale_items (
	id SERIAL NOT NULL,
	sale_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	unit_price INTEGER NOT NULL,
	unit_cost_snapshot INTEGER NOT NULL,
	line_total INTEGER NOT NULL,
	paid_amount INTEGER NOT NULL,
	remaining_amount INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(sale_id) REFERENCES sales (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_sale_items_id ON sale_items (id);
CREATE TABLE stock_movements (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	product_id INTEGER NOT NULL,
	movement_type VARCHAR(50) NOT NULL,
	quantity INTEGER NOT NULL,
	reference_type VARCHAR(50) NOT NULL,
	reference_id INTEGER NOT NULL,
	note VARCHAR(255),
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_stock_movements_id ON stock_movements (id);
CREATE INDEX ix_stock_movements_merchant_id ON stock_movements (merchant_id);
CREATE TABLE stock_reservations (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	source_type VARCHAR(50) NOT NULL,
	source_id INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	consumed_at TIMESTAMP WITHOUT TIME ZONE,
	released_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_stock_reservations_id ON stock_reservations (id);
CREATE INDEX ix_stock_reservations_merchant_id ON stock_reservations (merchant_id);
CREATE INDEX ix_stock_reservations_product_id ON stock_reservations (product_id);
CREATE INDEX ix_stock_reservations_product_status_expires ON stock_reservations (product_id, status, expires_at);
CREATE INDEX ix_stock_reservations_source ON stock_reservations (source_type, source_id);
CREATE TABLE supplier_payments (
	id SERIAL NOT NULL,
	merchant_id INTEGER,
	purchase_id INTEGER NOT NULL,
	supplier_id INTEGER,
	amount INTEGER NOT NULL,
	channel VARCHAR(30) NOT NULL,
	reference VARCHAR(100),
	paid_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(purchase_id) REFERENCES purchases (id),
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id)
);
CREATE INDEX ix_supplier_payments_id ON supplier_payments (id);
CREATE INDEX ix_supplier_payments_merchant_id ON supplier_payments (merchant_id);
CREATE TABLE online_order_items (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	product_name_snapshot VARCHAR(150) NOT NULL,
	unit_snapshot VARCHAR(30) NOT NULL,
	quantity INTEGER NOT NULL,
	unit_price_snapshot INTEGER NOT NULL,
	line_total INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(order_id) REFERENCES online_orders (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_online_order_items_id ON online_order_items (id);
CREATE INDEX ix_online_order_items_merchant_id ON online_order_items (merchant_id);
CREATE INDEX ix_online_order_items_order_id ON online_order_items (order_id);
CREATE INDEX ix_online_order_items_product_id ON online_order_items (product_id);
CREATE TABLE payment_allocations (
	id SERIAL NOT NULL,
	payment_id INTEGER NOT NULL,
	sale_item_id INTEGER NOT NULL,
	allocated_amount INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(payment_id) REFERENCES payments (id),
	FOREIGN KEY(sale_item_id) REFERENCES sale_items (id)
);
CREATE INDEX ix_payment_allocations_id ON payment_allocations (id);
CREATE TABLE supplier_payment_allocations (
	id SERIAL NOT NULL,
	supplier_payment_id INTEGER NOT NULL,
	purchase_item_id INTEGER NOT NULL,
	allocated_amount INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(supplier_payment_id) REFERENCES supplier_payments (id),
	FOREIGN KEY(purchase_item_id) REFERENCES purchase_items (id)
);
CREATE INDEX ix_supplier_payment_allocations_id ON supplier_payment_allocations (id);
RESET ROLE;
