-- LAB ONLY. Rattrape le schema du laboratoire apres la fusion avec la ligne Shop
-- (001 a 005 restent inchangees). Ne pas appliquer sur Railway, Shop ou une base existante.
-- Online reste en LECTURE SEULE sur les tables du Shop : la sortie de stock a la finalisation
-- exige des droits d'ecriture qui sont une decision separee (voir ADR physique J4.3B).
SET ROLE j43a_owner;

ALTER TABLE merchants ADD COLUMN business_type VARCHAR(40) DEFAULT 'general_retail' NOT NULL;
ALTER TABLE merchants ADD COLUMN country_code VARCHAR(2);
ALTER TABLE merchants ADD COLUMN password_hash VARCHAR(255);

CREATE TABLE shops (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	name VARCHAR(150) NOT NULL,
	code VARCHAR(50) NOT NULL,
	address VARCHAR(255),
	currency_code VARCHAR(3) DEFAULT 'XOF' NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_shops_merchant_code UNIQUE (merchant_id, code),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id)
);
CREATE INDEX ix_shops_currency_code ON shops (currency_code);
CREATE INDEX ix_shops_id ON shops (id);
CREATE INDEX ix_shops_merchant_id ON shops (merchant_id);

CREATE TABLE shop_inventories (
	id SERIAL NOT NULL,
	merchant_id INTEGER NOT NULL,
	shop_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	stock INTEGER DEFAULT 0 NOT NULL,
	initial_stock INTEGER,
	threshold INTEGER DEFAULT 0 NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_shop_inventory_product UNIQUE (shop_id, product_id),
	FOREIGN KEY(merchant_id) REFERENCES merchants (id),
	FOREIGN KEY(shop_id) REFERENCES shops (id),
	FOREIGN KEY(product_id) REFERENCES products (id)
);
CREATE INDEX ix_shop_inventories_id ON shop_inventories (id);
CREATE INDEX ix_shop_inventories_merchant_id ON shop_inventories (merchant_id);
CREATE INDEX ix_shop_inventories_product_id ON shop_inventories (product_id);
CREATE INDEX ix_shop_inventories_shop_id ON shop_inventories (shop_id);

ALTER TABLE online_stores ADD COLUMN fulfilment_shop_id INTEGER REFERENCES shops (id);
ALTER TABLE online_stores ADD COLUMN stock_buffer INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE online_stores ADD COLUMN low_stock_threshold INTEGER DEFAULT 2 NOT NULL;
ALTER TABLE online_product_publications ADD COLUMN stock_buffer_override INTEGER;
ALTER TABLE online_product_publications ADD COLUMN stock_mode VARCHAR(20) DEFAULT 'tracked' NOT NULL;
ALTER TABLE online_product_publications ADD COLUMN daily_quantity INTEGER;

REVOKE ALL ON shops, shop_inventories FROM PUBLIC;
REVOKE ALL ON SEQUENCE shops_id_seq, shop_inventories_id_seq FROM PUBLIC;
ALTER TABLE shops ENABLE ROW LEVEL SECURITY;
ALTER TABLE shops FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON shops USING (merchant_id = NULLIF(current_setting('app.current_merchant_id', true), '')::integer) WITH CHECK (merchant_id = NULLIF(current_setting('app.current_merchant_id', true), '')::integer);
ALTER TABLE shop_inventories ENABLE ROW LEVEL SECURITY;
ALTER TABLE shop_inventories FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON shop_inventories USING (merchant_id = NULLIF(current_setting('app.current_merchant_id', true), '')::integer) WITH CHECK (merchant_id = NULLIF(current_setting('app.current_merchant_id', true), '')::integer);
GRANT SELECT, INSERT, UPDATE ON shops, shop_inventories TO j43a_core_runtime;
GRANT USAGE ON SEQUENCE shops_id_seq, shop_inventories_id_seq TO j43a_core_runtime;
GRANT SELECT ON shops, shop_inventories TO j43a_online_runtime;
