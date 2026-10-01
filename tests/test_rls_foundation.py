from app.shared.tenancy.rls import (
    BUSINESS_TRANSACTIONS_RLS_SQL,
    BUSINESS_TRANSACTIONS_SCHEMA_SQL,
)


def test_business_transactions_schema_is_additive():
    sql = BUSINESS_TRANSACTIONS_SCHEMA_SQL.lower()

    assert "create table if not exists business_transactions" in sql
    assert "merchant_id integer not null" in sql
    assert "sales" not in sql
    assert "alter table sales" not in sql


def test_business_transactions_rls_is_forced_and_tenant_scoped():
    sql = "\n".join(BUSINESS_TRANSACTIONS_RLS_SQL).lower()

    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "business_transactions_tenant_isolation" in sql
    assert "app.current_merchant_id" in sql
    assert "with check" in sql


def test_rls_context_is_transaction_local():
    from pathlib import Path

    source = Path("app/shared/tenancy/rls.py").read_text()

    assert "set_config(:key, :value, true)" in source
