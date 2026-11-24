from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


EXPECTED_TABLES: dict[str, set[str]] = {
    "online_stores": {
        "id",
        "merchant_id",
        "slug",
        "display_name",
        "business_type",
        "capabilities_json",
        "currency",
        "country_code",
        "seo_title",
        "seo_description",
        "canonical_domain",
        "address",
        "city",
        "postal_code",
        "latitude",
        "longitude",
        "is_active",
        "fulfilment_shop_id",
        "stock_buffer",
        "low_stock_threshold",
    },
    "online_product_publications": {
        "id",
        "merchant_id",
        "product_id",
        "is_published",
        "is_active",
        "show_price",
        "show_stock",
        "seo_slug",
        "seo_title",
        "seo_description",
        "stock_buffer_override",
    },
    "online_product_images": {
        "id",
        "merchant_id",
        "product_id",
        "image_url",
        "is_primary",
        "position",
    },
    "online_carts": {
        "id",
        "merchant_id",
        "store_id",
        "token",
        "status",
        "currency",
        "expires_at",
    },
    "online_cart_items": {
        "id",
        "merchant_id",
        "cart_id",
        "product_id",
        "quantity",
        "unit_price_snapshot",
    },
    "business_transactions": {
        "id",
        "merchant_id",
        "kind",
        "status",
        "currency",
        "subtotal_amount",
        "fee_amount",
        "total_amount",
        "payment_status",
    },
    "online_orders": {
        "id",
        "merchant_id",
        "store_id",
        "transaction_id",
        "cart_id",
        "reference",
        "status",
        "customer_name",
        "customer_phone",
        "delivery_mode",
        "delivery_address",
        "currency",
        "subtotal_amount",
        "delivery_amount",
        "total_amount",
        "payment_method",
        "payment_status",
    },
    "online_order_items": {
        "id",
        "merchant_id",
        "order_id",
        "product_id",
        "product_name_snapshot",
        "quantity",
        "unit_price_snapshot",
        "line_total",
    },
    "stock_reservations": {
        "id",
        "merchant_id",
        "product_id",
        "quantity",
        "source_type",
        "source_id",
        "status",
        "expires_at",
        "consumed_at",
        "released_at",
    },
    "web_push_subscriptions": {
        "id",
        "merchant_id",
        "endpoint",
        "p256dh",
        "auth",
        "is_active",
        "created_at",
        "updated_at",
    },
    "online_notifications": {
        "id",
        "source_event_id",
        "merchant_id",
        "aggregate_type",
        "aggregate_id",
        "recipient_role",
        "channel",
        "title",
        "body",
        "action_url",
        "status",
        "created_at",
        "read_at",
    },
    "outbox_events": {
        "id",
        "event_id",
        "merchant_id",
        "aggregate_type",
        "aggregate_id",
        "event_type",
        "payload",
        "status",
        "retry_count",
        "created_at",
        "published_at",
        "next_attempt_at",
        "processing_started_at",
        "provider_message_id",
    },
}


EXPECTED_INDEXES: dict[str, set[str]] = {
    "business_transactions": {
        "ix_business_transactions_merchant_id",
        "ix_business_transactions_shop_id",
        "ix_business_transactions_merchant_created_at",
        "ix_business_transactions_merchant_kind_status",
    },
    "online_stores": {
        "ix_online_stores_merchant_id",
        "ix_online_stores_slug",
    },
    "online_product_publications": {
        "ix_online_product_publications_merchant_id",
        "ix_online_product_publications_product_id",
    },
    "online_product_images": {
        "ix_online_product_images_merchant_id",
        "ix_online_product_images_product_id",
    },
    "online_orders": {
        "ix_online_orders_merchant_id",
        "ix_online_orders_store_id",
        "ix_online_orders_reference",
        "ix_online_orders_merchant_status",
        "ix_online_orders_store_created_at",
    },
    "online_order_items": {
        "ix_online_order_items_merchant_id",
        "ix_online_order_items_order_id",
        "ix_online_order_items_product_id",
    },
    "stock_reservations": {
        "ix_stock_reservations_product_status_expires",
        "ix_stock_reservations_source",
    },
    "web_push_subscriptions": {
        "ix_web_push_subscriptions_merchant_active",
    },
    "online_notifications": {
        "ix_online_notifications_merchant_status_created_at",
    },
    "outbox_events": {
        "ix_outbox_events_status_created_at",
        "ix_outbox_events_merchant_created_at",
        "ix_outbox_events_status_next_attempt_at",
    },
}


def audit_online_schema(*, db: Session) -> dict:
    inspector = inspect(db.get_bind())
    existing_tables = set(inspector.get_table_names())

    missing_tables = sorted(
        table
        for table in EXPECTED_TABLES
        if table not in existing_tables
    )

    missing_columns: dict[str, list[str]] = {}
    missing_indexes: dict[str, list[str]] = {}

    for table, expected_columns in EXPECTED_TABLES.items():
        if table not in existing_tables:
            continue
        actual_columns = {
            column["name"]
            for column in inspector.get_columns(table)
        }
        missing = sorted(expected_columns - actual_columns)
        if missing:
            missing_columns[table] = missing

    for table, expected_indexes in EXPECTED_INDEXES.items():
        if table not in existing_tables:
            continue
        actual_indexes = {
            index["name"]
            for index in inspector.get_indexes(table)
            if index.get("name")
        }
        missing = sorted(expected_indexes - actual_indexes)
        if missing:
            missing_indexes[table] = missing

    rls = _postgres_rls_audit(db=db)

    ready = not (
        missing_tables
        or missing_columns
        or missing_indexes
        or rls["missing_rls_tables"]
        or rls["missing_policies"]
    )

    return {
        "ready": ready,
        "read_only": True,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "rls": rls,
        "checked_tables": sorted(EXPECTED_TABLES),
    }



def _postgres_rls_audit(*, db: Session) -> dict:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return {
            "checked": False,
            "reason": "not_postgresql",
            "missing_rls_tables": [],
            "missing_policies": [],
        }

    expected = {
        "business_transactions": "business_transactions_tenant_isolation",
        "outbox_events": "outbox_events_tenant_isolation",
        "online_notifications": "online_notifications_tenant_isolation",
        "web_push_subscriptions": "web_push_subscriptions_tenant_isolation",
    }

    rows = db.execute(
        text(
            """
            SELECT
                c.relname AS table_name,
                c.relrowsecurity AS rls_enabled,
                c.relforcerowsecurity AS rls_forced
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname IN ('business_transactions', 'outbox_events', 'online_notifications', 'web_push_subscriptions')
            """
        )
    ).mappings().all()

    by_table = {row["table_name"]: row for row in rows}
    missing_rls_tables = sorted(
        table
        for table in expected
        if table not in by_table
        or not by_table[table]["rls_enabled"]
        or not by_table[table]["rls_forced"]
    )

    policy_rows = db.execute(
        text(
            """
            SELECT tablename, policyname
            FROM pg_policies
            WHERE schemaname = current_schema()
              AND tablename IN ('business_transactions', 'outbox_events', 'online_notifications', 'web_push_subscriptions')
            """
        )
    ).mappings().all()
    policies = {
        (row["tablename"], row["policyname"])
        for row in policy_rows
    }
    missing_policies = sorted(
        f"{table}.{policy}"
        for table, policy in expected.items()
        if (table, policy) not in policies
    )

    return {
        "checked": True,
        "missing_rls_tables": missing_rls_tables,
        "missing_policies": missing_policies,
    }
