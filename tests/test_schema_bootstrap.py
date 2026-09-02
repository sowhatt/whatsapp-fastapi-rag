from sqlalchemy import create_engine, inspect

from app.db.schema import create_base_schema


def test_create_base_schema_bootstraps_an_empty_database():
    engine = create_engine("sqlite://")

    create_base_schema(engine)

    table_names = set(inspect(engine).get_table_names())
    assert {
        "merchants",
        "categories",
        "products",
        "customers",
        "suppliers",
        "sales",
        "sale_items",
        "purchases",
        "purchase_items",
        "financial_entries",
    } <= table_names
