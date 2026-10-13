from app.domains.online.internal.schema import ONLINE_SCHEMA_SQL
from app.domains.online.internal.order_schema import ONLINE_ORDER_SCHEMA_SQL


def test_online_store_additive_migrations_are_idempotent():
    sql = "\n".join(ONLINE_SCHEMA_SQL).lower()

    required = (
        "business_type",
        "capabilities_json",
        "seo_title",
        "seo_description",
        "canonical_domain",
        "address",
        "city",
        "postal_code",
        "latitude",
        "longitude",
    )

    for column in required:
        assert (
            f"alter table online_stores add column if not exists {column}"
            in sql
        )


def test_online_schema_does_not_alter_legacy_shop_tables():
    sql = "\n".join(ONLINE_SCHEMA_SQL).lower()

    for table in (
        "sales",
        "payments",
        "financial_entries",
        "stock_movements",
        "product_publications",
    ):
        assert f"alter table {table} " not in sql



def test_online_order_payment_method_migration_is_idempotent():
    sql = "\n".join(ONLINE_ORDER_SCHEMA_SQL).lower()
    assert (
        "alter table online_orders add column if not exists payment_method"
        in sql
    )
