from sqlalchemy import Connection, text


OUTBOX_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outbox_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(36) NOT NULL UNIQUE,
    merchant_id INTEGER NOT NULL,
    aggregate_type VARCHAR(80) NOT NULL,
    aggregate_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(120) NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,
    payload JSON NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    published_at TIMESTAMP NULL,
    next_attempt_at TIMESTAMP NULL,
    processing_started_at TIMESTAMP NULL,
    provider_message_id VARCHAR(255) NULL
)
"""

OUTBOX_ALTER_SQL = (
    "ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP NULL",
    "ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP NULL",
    "ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS provider_message_id VARCHAR(255) NULL",
)

OUTBOX_INDEX_SQL = (
    """
    CREATE INDEX IF NOT EXISTS ix_outbox_events_status_created_at
    ON outbox_events (status, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_outbox_events_merchant_created_at
    ON outbox_events (merchant_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_outbox_events_status_next_attempt_at
    ON outbox_events (status, next_attempt_at)
    """,
)

OUTBOX_RLS_SQL = (
    "ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS outbox_events_tenant_isolation ON outbox_events",
    """
    CREATE POLICY outbox_events_tenant_isolation
    ON outbox_events
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


def install_outbox_schema(connection: Connection) -> None:
    connection.execute(text(OUTBOX_SCHEMA_SQL))
    for statement in OUTBOX_ALTER_SQL:
        connection.execute(text(statement))
    for statement in OUTBOX_INDEX_SQL:
        connection.execute(text(statement))
    for statement in OUTBOX_RLS_SQL:
        connection.execute(text(statement))
