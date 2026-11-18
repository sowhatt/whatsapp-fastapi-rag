"""Explicit, offline operator commands. Never imported by FastAPI startup.

No URL is read from app settings or .env. A database name and URL are mandatory.
Data correction uses a reviewed manifest; costs and existing sale numbers cannot
be rewritten. Use --apply only after reviewing the default read-only plan.
"""
import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text, update

from app.db.compatibility import check_schema_compatibility
from app.db.schema import Base

OWNER_TABLES = {
    "customers", "suppliers", "products", "categories", "sales", "purchases",
    "financial_entries", "payments", "supplier_payments", "stock_movements",
    "transaction_events",
}
CURRENCIES = [
    ("EUR", "Euro", "EUR", 2), ("XOF", "Franc CFA BCEAO", "FCFA", 0),
    ("USD", "Dollar americain", "USD", 2), ("NGN", "Naira nigerian", "NGN", 2),
    ("GHS", "Cedi ghaneen", "GHS", 2), ("GBP", "Livre sterling", "GBP", 2),
]


def initialize_empty(connection):
    if inspect(connection).get_table_names(schema="public"):
        raise ValueError("init-empty refuses any existing public table")
    # Auth tables are owned by the explicit consolidated 005 migration.
    # Auth models may already be registered when the combined app is imported.
    Base.metadata.create_all(connection, tables=[
        table for table in Base.metadata.sorted_tables
        if not table.name.startswith(("merchant_auth_", "merchant_pin_", "merchant_passkey"))
    ])
    connection.execute(Base.metadata.tables["currencies"].insert(), [
        dict(code=code, name=name, symbol=symbol, decimals=decimals, is_active=True)
        for code, name, symbol, decimals in CURRENCIES
    ])


def validate_manifest(manifest):
    if not isinstance(manifest.get("migration_id"), str) or not manifest["migration_id"].strip():
        raise ValueError("migration_id required")
    if not isinstance(manifest.get("approved_by"), str) or not manifest["approved_by"].strip():
        raise ValueError("approved_by required")
    if manifest["migration_id"].startswith("EXAMPLE") or manifest["approved_by"].startswith("REPLACE"):
        raise ValueError("example manifest is not executable; supply reviewed values")
    changes = manifest.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("nonempty changes required")
    seen = set()
    for change in changes:
        table, column = change["table"], change["column"]
        allowed = (table in OWNER_TABLES and column == "merchant_id") or (table, column) in {
            ("sales", "sale_number"), ("merchants", "subscription_status")
        }
        if not allowed or "expected" not in change or change["expected"] is not None:
            raise ValueError("only explicit NULL repairs allowed; no historical cost/number overwrite")
        if type(change["id"]) is not int or change["id"] <= 0 or not str(change.get("evidence", "")).strip():
            raise ValueError("positive row id and evidence required")
        if column == "subscription_status":
            if change["value"] not in {"pilot", "trialing", "active", "grace", "expired", "suspended"}:
                raise ValueError("invalid subscription status")
        elif type(change["value"]) is not int or change["value"] <= 0:
            raise ValueError("positive merchant id / sale number required")
        key = (table, change["id"], column)
        if key in seen:
            raise ValueError("duplicate correction")
        seen.add(key)


def validate_tenant_links(connection):
    # Block contradictions, including indirect historical item relationships.
    for table in Base.metadata.sorted_tables:
        if "merchant_id" not in table.c:
            continue
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent is table or "merchant_id" not in parent.c or fk.parent.name == "merchant_id":
                continue
            invalid = connection.execute(select(table.c.id).join(parent, fk.parent == fk.column).where(
                table.c.merchant_id.is_not(None), parent.c.merchant_id.is_not(None),
                table.c.merchant_id != parent.c.merchant_id,
            ).limit(1)).first()
            if invalid:
                raise ValueError(f"cross-merchant relationship: {table.name}.{fk.parent.name}")
    for items, parent, parent_id in [("sale_items", "sales", "sale_id"), ("purchase_items", "purchases", "purchase_id")]:
        invalid = connection.execute(text(f"""
            SELECT 1 FROM public.{items} i
            JOIN public.{parent} p ON p.id = i.{parent_id}
            JOIN public.products product ON product.id = i.product_id
            WHERE p.merchant_id IS NOT NULL AND product.merchant_id IS NOT NULL
              AND p.merchant_id <> product.merchant_id LIMIT 1
        """)).first()
        if invalid:
            raise ValueError(f"cross-merchant product: {items}")


def correct_data(connection, manifest, apply=False):
    validate_manifest(manifest)
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    if apply:
        # Transactional journal, serialized operator jobs; no FastAPI dependency.
        connection.execute(text("SELECT pg_advisory_xact_lock(1847001029)"))
        connection.execute(text("""CREATE TABLE IF NOT EXISTS public.shop_p0_migrations (
            migration_id TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL,
            manifest JSONB NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""))
        existing = connection.execute(text("SELECT manifest_sha256 FROM public.shop_p0_migrations WHERE migration_id = :id"), {"id": manifest["migration_id"]}).scalar_one_or_none()
        if existing:
            if existing != digest:
                raise ValueError("migration id already used with different content")
            return {"status": "already_applied", "sha256": digest}
        # Offline maintenance only. Lock all model tables to prevent concurrent
        # business writes while relationships and explicit assignments are checked.
        names = ", ".join('public."' + t + '"' for t in sorted(Base.metadata.tables))
        connection.execute(text(f"LOCK TABLE {names} IN SHARE ROW EXCLUSIVE MODE"))
    for change in manifest["changes"]:
        table = Base.metadata.tables[change["table"]]
        column = table.c[change["column"]]
        query = select(table).where(table.c.id == change["id"])
        row = connection.execute(query).mappings().one()
        if row[change["column"]] != change["expected"]:
            raise ValueError(f"stale expected value: {table.name} id={change['id']}")
        if change["column"] == "merchant_id":
            if not connection.execute(select(Base.metadata.tables["merchants"].c.id).where(Base.metadata.tables["merchants"].c.id == change["value"])).first():
                raise ValueError("target merchant missing")
        if change["column"] == "sale_number" and row["merchant_id"] is None:
            raise ValueError("sale ownership must be established before assigning a number")
        if apply:
            result = connection.execute(update(table).where(table.c.id == change["id"], column.is_(None)).values({change["column"]: change["value"]}))
            if result.rowcount != 1:
                raise ValueError("concurrent correction")
    if apply:
        validate_tenant_links(connection)
        connection.execute(text("INSERT INTO public.shop_p0_migrations (migration_id, manifest_sha256, manifest) VALUES (:id, :digest, CAST(:manifest AS jsonb))"),
                           {"id": manifest["migration_id"], "digest": digest, "manifest": json.dumps(manifest)})
    return {"status": "applied" if apply else "plan_only", "changes": len(manifest["changes"]), "sha256": digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "init-empty", "correct-data"])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    if engine.dialect.name != "postgresql":
        raise ValueError("PostgreSQL required")
    with engine.connect() as connection:
        with connection.begin():
            if not args.apply or args.command == "check":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL search_path TO public, pg_catalog"))
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL statement_timeout = '60s'"))
            if connection.execute(text("SELECT current_database()")).scalar_one() != args.expected_database:
                raise ValueError("database identity mismatch")
            if args.command == "init-empty":
                if inspect(connection).get_table_names(schema="public"):
                    raise ValueError("init-empty refuses existing tables")
                if args.apply:
                    initialize_empty(connection)
                print(json.dumps({"command": "init-empty", "applied": args.apply, "tables": len(Base.metadata.tables), "currencies": 6}))
            elif args.command == "correct-data":
                if not args.manifest:
                    raise ValueError("--manifest required")
                print(json.dumps(correct_data(connection, json.loads(args.manifest.read_text()), args.apply)))
    if args.command == "check":
        check_schema_compatibility(engine)
        print("compatible; no migration executed")
    engine.dispose()


if __name__ == "__main__":
    main()
