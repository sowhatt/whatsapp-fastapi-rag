"""PostgreSQL Row-Level Security for new Whatzabi domains.

S0.4 deliberately enables database-level tenant isolation only on new
S0 tables first. Legacy Whatzabi Shop tables keep their existing SQLAlchemy
tenant filter until the RLS rollout is validated in staging.
"""
from __future__ import annotations

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

MERCHANT_GUC = "app.current_merchant_id"
RLS_BYPASS_GUC = "app.rls_bypass"


BUSINESS_TRANSACTIONS_SCHEMA_SQL = """
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
"""

BUSINESS_TRANSACTIONS_INDEX_SQL = (
    """
    CREATE INDEX IF NOT EXISTS ix_business_transactions_merchant_id
    ON business_transactions (merchant_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_business_transactions_shop_id
    ON business_transactions (shop_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_business_transactions_merchant_created_at
    ON business_transactions (merchant_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_business_transactions_merchant_kind_status
    ON business_transactions (merchant_id, kind, status)
    """,
)

BUSINESS_TRANSACTIONS_RLS_SQL = (
    "ALTER TABLE business_transactions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE business_transactions FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS business_transactions_tenant_isolation ON business_transactions",
    """
    CREATE POLICY business_transactions_tenant_isolation
    ON business_transactions
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


def install_foundation_rls(connection: Connection) -> None:
    """Create the S0 transaction table and its tenant RLS policy idempotently."""
    connection.execute(text(BUSINESS_TRANSACTIONS_SCHEMA_SQL))
    for statement in BUSINESS_TRANSACTIONS_INDEX_SQL:
        connection.execute(text(statement))
    for statement in BUSINESS_TRANSACTIONS_RLS_SQL:
        connection.execute(text(statement))


def apply_rls_context(
    db: Session,
    *,
    merchant_id: int,
    bypass: bool = False,
) -> None:
    """Bind PostgreSQL RLS variables to the current SQL transaction.

    SET LOCAL semantics are implemented through PostgreSQL set_config(..., true),
    so values disappear automatically at commit/rollback and cannot leak through
    the connection pool.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return

    db.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": MERCHANT_GUC, "value": str(merchant_id)},
    )
    db.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": RLS_BYPASS_GUC, "value": "true" if bypass else "false"},
    )


def apply_rls_bypass(db: Session, *, enabled: bool) -> None:
    """Explicit administration escape hatch, transaction-local only."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": RLS_BYPASS_GUC, "value": "true" if enabled else "false"},
    )
