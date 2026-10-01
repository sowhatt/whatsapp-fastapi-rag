from app.shared.tenancy.rls import BUSINESS_TRANSACTIONS_RLS_SQL


LEGACY_SHOP_TABLES = {
    "sales",
    "products",
    "customers",
    "payments",
    "stock_movements",
    "financial_entries",
}


def test_s0_rls_does_not_modify_legacy_shop_tables():
    sql = "\n".join(BUSINESS_TRANSACTIONS_RLS_SQL).lower()

    for table in LEGACY_SHOP_TABLES:
        assert f"alter table {table} enable row level security" not in sql
        assert f"alter table {table} force row level security" not in sql


def test_s0_rls_targets_only_business_transactions():
    sql = "\n".join(BUSINESS_TRANSACTIONS_RLS_SQL).lower()

    assert "alter table business_transactions enable row level security" in sql
    assert "alter table business_transactions force row level security" in sql
