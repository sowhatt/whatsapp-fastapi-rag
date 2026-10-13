from sqlalchemy import Connection, text


BUSINESS_TRANSACTION_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS business_transactions (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        shop_id INTEGER NULL,
        kind VARCHAR(30) NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'draft',
        currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
        subtotal_amount INTEGER NOT NULL DEFAULT 0,
        tax_amount INTEGER NOT NULL DEFAULT 0,
        fee_amount INTEGER NOT NULL DEFAULT 0,
        discount_amount INTEGER NOT NULL DEFAULT 0,
        total_amount INTEGER NOT NULL DEFAULT 0,
        payment_status VARCHAR(30) NOT NULL DEFAULT 'unpaid',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_business_transactions_merchant_id ON business_transactions (merchant_id)",
    "CREATE INDEX IF NOT EXISTS ix_business_transactions_shop_id ON business_transactions (shop_id)",
    """
    CREATE INDEX IF NOT EXISTS ix_business_transactions_merchant_created_at
    ON business_transactions (merchant_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_business_transactions_merchant_kind_status
    ON business_transactions (merchant_id, kind, status)
    """,
)


def install_business_transaction_schema(connection: Connection) -> None:
    for statement in BUSINESS_TRANSACTION_SCHEMA_SQL:
        connection.execute(text(statement))
