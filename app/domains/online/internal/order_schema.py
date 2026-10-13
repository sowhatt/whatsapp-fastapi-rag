from sqlalchemy import Connection, text


ONLINE_ORDER_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS online_orders (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        store_id INTEGER NOT NULL REFERENCES online_stores(id),
        transaction_id INTEGER NOT NULL UNIQUE REFERENCES business_transactions(id),
        cart_id INTEGER NOT NULL UNIQUE REFERENCES online_carts(id),
        reference VARCHAR(20) NOT NULL UNIQUE,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        customer_name VARCHAR(150) NOT NULL,
        customer_phone VARCHAR(40) NOT NULL,
        delivery_mode VARCHAR(20) NOT NULL DEFAULT 'pickup',
        delivery_address VARCHAR(500) NULL,
        notes VARCHAR(500) NULL,
        currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
        subtotal_amount INTEGER NOT NULL DEFAULT 0,
        delivery_amount INTEGER NOT NULL DEFAULT 0,
        total_amount INTEGER NOT NULL DEFAULT 0,
        payment_method VARCHAR(30) NOT NULL DEFAULT 'cash_on_delivery',
        payment_status VARCHAR(30) NOT NULL DEFAULT 'cash_on_delivery',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE online_orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(30) NOT NULL DEFAULT 'cash_on_delivery'",
    "CREATE INDEX IF NOT EXISTS ix_online_orders_merchant_id ON online_orders (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_orders_store_id ON online_orders (store_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_orders_reference ON online_orders (reference)",
    "CREATE INDEX IF NOT EXISTS ix_online_orders_merchant_status ON online_orders (merchant_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_online_orders_store_created_at ON online_orders (store_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS online_order_items (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        order_id INTEGER NOT NULL REFERENCES online_orders(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        product_name_snapshot VARCHAR(150) NOT NULL,
        unit_snapshot VARCHAR(30) NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price_snapshot INTEGER NOT NULL,
        line_total INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_online_order_items_merchant_id ON online_order_items (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_order_items_order_id ON online_order_items (order_id)",
    "CREATE INDEX IF NOT EXISTS ix_online_order_items_product_id ON online_order_items (product_id)",
)


def install_online_order_schema(connection: Connection) -> None:
    for statement in ONLINE_ORDER_SCHEMA_SQL:
        connection.execute(text(statement))
