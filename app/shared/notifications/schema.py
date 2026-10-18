from sqlalchemy import Connection, text


ONLINE_NOTIFICATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS online_notifications (
    id SERIAL PRIMARY KEY,
    source_event_id VARCHAR(36) NOT NULL UNIQUE,
    merchant_id INTEGER NOT NULL,
    aggregate_type VARCHAR(80) NOT NULL,
    aggregate_id VARCHAR(100) NOT NULL,
    recipient_role VARCHAR(30) NOT NULL,
    channel VARCHAR(30) NOT NULL,
    title VARCHAR(180) NOT NULL,
    body TEXT NOT NULL,
    action_url VARCHAR(2000) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'unread',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    read_at TIMESTAMP NULL
)
"""

ONLINE_NOTIFICATIONS_INDEX_SQL = (
    """
    CREATE INDEX IF NOT EXISTS ix_online_notifications_merchant_status_created_at
    ON online_notifications (merchant_id, status, created_at)
    """,
)

ONLINE_NOTIFICATIONS_RLS_SQL = (
    "ALTER TABLE online_notifications ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE online_notifications FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS online_notifications_tenant_isolation ON online_notifications",
    """
    CREATE POLICY online_notifications_tenant_isolation
    ON online_notifications
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


def install_online_notifications_schema(connection: Connection) -> None:
    connection.execute(text(ONLINE_NOTIFICATIONS_SCHEMA_SQL))
    for statement in ONLINE_NOTIFICATIONS_INDEX_SQL:
        connection.execute(text(statement))
    for statement in ONLINE_NOTIFICATIONS_RLS_SQL:
        connection.execute(text(statement))
