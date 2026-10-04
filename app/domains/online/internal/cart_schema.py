from sqlalchemy import Connection, text


ONLINE_CART_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS online_carts (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        store_id INTEGER NOT NULL REFERENCES online_stores(id),
        token VARCHAR(36) NOT NULL UNIQUE,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMP NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_online_carts_merchant_id ON online_carts (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_carts_store_id ON online_carts (store_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_carts_merchant_status ON online_carts (merchant_id, status)",
    """
    CREATE TABLE IF NOT EXISTS online_cart_items (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        cart_id INTEGER NOT NULL REFERENCES online_carts(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL DEFAULT 1,
        unit_price_snapshot INTEGER NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_online_cart_item_cart_product UNIQUE (cart_id, product_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_online_cart_items_merchant_id ON online_cart_items (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_cart_items_cart_id ON online_cart_items (cart_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_cart_items_product_id ON online_cart_items (product_id)",
)


def install_online_cart_schema(connection: Connection) -> None:
    for statement in ONLINE_CART_SCHEMA_SQL:
        connection.execute(text(statement))
