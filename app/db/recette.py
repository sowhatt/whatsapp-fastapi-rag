"""Explicit initialization for a NEW independent Shop database, never a startup hook."""
import argparse
import json
from pathlib import Path
import re

from sqlalchemy import create_engine, inspect, text

from app.db.migrate import initialize_empty

SQL_FILES = (
    "bi_01_materialized_views.sql", "bi_01_financial_position.sql",
    "bi_01_inventory_history.sql", "bi_02_shop_analytics.sql",
)


def initialize_recette(connection):
    if connection.dialect.name != "postgresql":
        raise ValueError("PostgreSQL required")
    if inspect(connection).get_table_names(schema="public") or inspect(connection).get_view_names(schema="public") or inspect(connection).get_materialized_view_names(schema="public"):
        raise ValueError("init-recette refuses existing public relations")
    initialize_empty(connection)
    root = Path(__file__).resolve().parents[1] / "analytics/sql"
    for filename in SQL_FILES:
        # Keep the reference calculations. On a new database, destructive DROP
        # clauses are neither necessary nor authorized by this initializer.
        sql = re.sub(r"DROP MATERIALIZED VIEW IF EXISTS\s+\w+\s+CASCADE;", "", (root / filename).read_text())
        connection.execute(text(sql))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    if engine.dialect.name != "postgresql":
        raise ValueError("PostgreSQL required")
    with engine.begin() as connection:
        if not args.apply:
            connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL search_path TO public, pg_catalog"))
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '60s'"))
        if connection.execute(text("SELECT current_database()")).scalar_one() != args.expected_database:
            raise ValueError("database identity mismatch")
        if not 180000 <= int(connection.execute(text("SHOW server_version_num")).scalar_one()) < 190000:
            raise ValueError("This independent recette artifact is qualified for PostgreSQL 18")
        inspector = inspect(connection)
        if inspector.get_table_names(schema="public") or inspector.get_view_names(schema="public") or inspector.get_materialized_view_names(schema="public"):
            raise ValueError("init-recette refuses existing public relations")
        if args.apply:
            initialize_recette(connection)
        print(json.dumps({"applied": args.apply, "mode": "new-independent-database-only", "analytics": list(SQL_FILES)}))
    engine.dispose()


if __name__ == "__main__":
    main()
