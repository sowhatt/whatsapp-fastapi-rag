from app.shared.outbox.schema import OUTBOX_RLS_SQL


def test_outbox_is_tenant_protected():
    sql = "\n".join(OUTBOX_RLS_SQL).lower()

    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "app.current_merchant_id" in sql
    assert "with check" in sql
