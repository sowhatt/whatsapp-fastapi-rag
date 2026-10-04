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
        template VARCHAR(30) NOT NULL DEFAULT 'essential',
        currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
        country_code VARCHAR(2) NOT NULL DEFAULT 'BJ',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_online_stores_merchant_id ON online_stores (merchant_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_online_stores_slug ON online_stores (slug)",
    """
    CREATE TABLE IF NOT EXISTS product_publications (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        is_published BOOLEAN NOT NULL DEFAULT FALSE,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        show_price BOOLEAN NOT NULL DEFAULT TRUE,
        show_stock BOOLEAN NOT NULL DEFAULT FALSE,
        description VARCHAR(500) NULL,
        display_order INTEGER NOT NULL DEFAULT 0,
        published_at TIMESTAMP NULL,
        CONSTRAINT uq_product_publication_merchant_product UNIQUE (merchant_id, product_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_product_publications_merchant_id ON product_publications (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_product_publications_product_id ON product_publications (product_id)",
    """
    CREATE TABLE IF NOT EXISTS product_images (
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
    "CREATE INDEX IF NOT EXISTS ix_product_images_merchant_id ON product_images (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_product_images_product_id ON product_images (product_id)",
)


def install_online_schema(connection: Connection) -> None:
    for statement in ONLINE_SCHEMA_SQL:
        connection.execute(text(statement))
