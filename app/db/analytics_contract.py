"""Read-only checks for the reference Finance schema qualified on PostgreSQL 18."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import inspect, text


def inspect_analytics(connection):
    root = Path(__file__).resolve().parent
    contract = json.loads((root / "analytics-contract.json").read_text())
    problems = []
    for name, digest in contract["sql_sha256"].items():
        if hashlib.sha256((root.parent / "analytics/sql" / name).read_bytes()).hexdigest() != digest:
            problems.append(f"unqualified analytics source: {name}")
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema="public"))
    views = {row["matviewname"]: row for row in connection.execute(text(
        "SELECT matviewname, definition, ispopulated FROM pg_catalog.pg_matviews WHERE schemaname='public'"
    )).mappings()}
    for name, expected in contract["relations"].items():
        materialized = expected["kind"] == "materialized_view"
        if name not in (views if materialized else tables):
            problems.append(f"missing analytics relation: {name}; explicit init-recette required")
            continue
        actual = {c["name"]: str(c["type"].compile(dialect=connection.dialect)) for c in inspector.get_columns(name, schema="public")}
        if any(actual.get(col) != kind for col, kind in expected["columns"].items()):
            problems.append(f"incompatible analytics columns: {name}")
        if materialized:
            if not views[name]["ispopulated"]:
                problems.append(f"unpopulated analytics view: {name}")
            # Same reference calculations, not merely a matching relation name.
            definition = connection.execute(text("SELECT pg_get_viewdef(CAST(:name AS regclass), true)"), {"name": "public." + name}).scalar_one()
            digest = hashlib.sha256(" ".join(definition.split()).encode()).hexdigest()
            if digest != expected["definition_sha256"]:
                problems.append(f"unqualified analytics definition: {name}")
            indexes = inspector.get_indexes(name, schema="public")
            for keys in expected["unique_keys"]:
                if not any(i["unique"] and i["column_names"] == keys and not i.get("dialect_options", {}).get("postgresql_where") for i in indexes):
                    problems.append(f"missing analytics unique index: {name}")
    return problems
