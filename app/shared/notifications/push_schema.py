from sqlalchemy import Connection, text


WEB_PUSH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS web_push_subscriptions (
    id SERIAL PRIMARY KEY,
    merchant_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh VARCHAR(255) NOT NULL,
    auth VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
)
"""

WEB_PUSH_INDEX_SQL = (
    """
    CREATE INDEX IF NOT EXISTS ix_web_push_subscriptions_merchant_active
    ON web_push_subscriptions (merchant_id, is_active)
    """,
)

WEB_PUSH_RLS_SQL = (
    "ALTER TABLE web_push_subscriptions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE web_push_subscriptions FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS web_push_subscriptions_tenant_isolation ON web_push_subscriptions",
    """
    CREATE POLICY web_push_subscriptions_tenant_isolation
    ON web_push_subscriptions
    USING (
        current_setting('app.rls_bypass', true) = 'true'
        OR merchant_id = NULLIF(
            current_setting('app.current_merchant_id', true),
            ''
        )::INTEGER
    )
    WITH CHECK (
        current_setting('app.rls_bypass', true) = 'true'
        OR merchant_id = NULLIF(
            current_setting('app.current_merchant_id', true),
            ''
        )::INTEGER
    )
    """,
)


def install_web_push_schema(connection: Connection) -> None:
    connection.execute(text(WEB_PUSH_SCHEMA_SQL))
    for statement in WEB_PUSH_INDEX_SQL:
        connection.execute(text(statement))
    for statement in WEB_PUSH_RLS_SQL:
        connection.execute(text(statement))
