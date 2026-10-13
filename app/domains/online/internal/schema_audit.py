from __future__ import annotations

from sqlalchemy import inspect
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
    "business_transactions": {
        "ix_business_transactions_merchant_id",
        "ix_business_transactions_shop_id",
        "ix_business_transactions_merchant_created_at",
        "ix_business_transactions_merchant_kind_status",
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
    },
}


EXPECTED_INDEXES: dict[str, set[str]] = {
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
    "outbox_events": {
        "ix_outbox_events_status_created_at",
        "ix_outbox_events_merchant_created_at",
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

    ready = not (
        missing_tables
        or missing_columns
        or missing_indexes
    )

    return {
        "ready": ready,
        "read_only": True,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "checked_tables": sorted(EXPECTED_TABLES),
    }
