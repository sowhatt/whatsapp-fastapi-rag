from sqlalchemy import Connection, text


STOCK_RESERVATION_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS stock_reservations (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL,
        source_type VARCHAR(50) NOT NULL,
        source_id INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        expires_at TIMESTAMP NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        consumed_at TIMESTAMP NULL,
        released_at TIMESTAMP NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stock_reservations_merchant_id
    ON stock_reservations (merchant_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stock_reservations_product_id
    ON stock_reservations (product_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stock_reservations_product_status_expires
    ON stock_reservations (product_id, status, expires_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_stock_reservations_source
    ON stock_reservations (source_type, source_id)
    """,
)


def install_stock_reservation_schema(connection: Connection) -> None:
    for statement in STOCK_RESERVATION_SCHEMA_SQL:
        connection.execute(text(statement))
