from sqlalchemy import Connection, text

ONLINE_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS online_stores (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL UNIQUE REFERENCES merchants(id),
        slug VARCHAR(80) NOT NULL UNIQUE,
        display_name VARCHAR(150) NOT NULL,
        description VARCHAR(500) NULL,
        logo_url VARCHAR(1000) NULL,
        banner_url VARCHAR(1000) NULL,
        primary_color VARCHAR(20) NULL,
        accent_color VARCHAR(20) NULL,
        business_type VARCHAR(30) NOT NULL DEFAULT 'commerce',
        capabilities_json TEXT NULL,
        template VARCHAR(30) NOT NULL DEFAULT 'essential',
        currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
        country_code VARCHAR(2) NOT NULL DEFAULT 'BJ',
        seo_title VARCHAR(180) NULL,
        seo_description VARCHAR(320) NULL,
        canonical_domain VARCHAR(255) NULL,
        address VARCHAR(300) NULL,
        city VARCHAR(120) NULL,
        postal_code VARCHAR(30) NULL,
        latitude VARCHAR(40) NULL,
        longitude VARCHAR(40) NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS online_product_publications (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        is_published BOOLEAN NOT NULL DEFAULT FALSE,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        show_price BOOLEAN NOT NULL DEFAULT TRUE,
        show_stock BOOLEAN NOT NULL DEFAULT FALSE,
        description VARCHAR(500) NULL,
        seo_slug VARCHAR(120) NULL,
        seo_title VARCHAR(180) NULL,
        seo_description VARCHAR(320) NULL,
        display_order INTEGER NOT NULL DEFAULT 0,
        published_at TIMESTAMP NULL,
        CONSTRAINT uq_online_product_publication_merchant_product UNIQUE (merchant_id, product_id)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_online_product_publication_merchant_seo_slug
    ON online_product_publications (merchant_id, seo_slug)
    WHERE seo_slug IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS online_product_images (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        image_url VARCHAR(1000) NOT NULL,
        storage_key VARCHAR(500) NULL,
        is_primary BOOLEAN NOT NULL DEFAULT FALSE,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS seo_title VARCHAR(180) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS seo_description VARCHAR(320) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS canonical_domain VARCHAR(255) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS address VARCHAR(300) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS city VARCHAR(120) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS postal_code VARCHAR(30) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS latitude VARCHAR(40) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS longitude VARCHAR(40) NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS business_type VARCHAR(30) NOT NULL DEFAULT 'commerce'",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS capabilities_json TEXT NULL",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS fulfilment_shop_id INTEGER NULL REFERENCES shops(id)",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS stock_buffer INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE online_stores ADD COLUMN IF NOT EXISTS low_stock_threshold INTEGER NOT NULL DEFAULT 2",
    "ALTER TABLE online_product_publications ADD COLUMN IF NOT EXISTS stock_buffer_override INTEGER NULL",
    "ALTER TABLE online_product_publications ADD COLUMN IF NOT EXISTS stock_mode VARCHAR(20) NOT NULL DEFAULT 'tracked'",
    "ALTER TABLE online_product_publications ADD COLUMN IF NOT EXISTS daily_quantity INTEGER NULL",
    "CREATE INDEX IF NOT EXISTS ix_online_stores_merchant_id ON online_stores (merchant_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_online_stores_slug ON online_stores (slug)",
    "CREATE INDEX IF NOT EXISTS ix_online_product_publications_merchant_id ON online_product_publications (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_product_publications_product_id ON online_product_publications (product_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_product_images_merchant_id ON online_product_images (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_product_images_product_id ON online_product_images (product_id)",
)

def install_online_schema(connection: Connection) -> None:
    for statement in ONLINE_SCHEMA_SQL:
        connection.execute(text(statement))
