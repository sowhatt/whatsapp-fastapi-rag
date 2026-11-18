"""Read-only startup contract. Schema/data repair belongs to an explicit operator job."""
from sqlalchemy import Float, UniqueConstraint, inspect, text
from sqlalchemy.engine import Engine

from app.db.schema import Base  # register the reference models, without create_all
from app.db.analytics_contract import inspect_analytics


class SchemaCompatibilityError(RuntimeError):
    pass


def _predicate(value):
    return "".join(str(value or "").lower().replace("(", "").replace(")", "").split())


def _type_name(column_type, dialect):
    # PostgreSQL reflects SQL FLOAT without precision as DOUBLE PRECISION.
    compiled = str(column_type.compile(dialect=dialect))
    if compiled in {"REAL", "DOUBLE PRECISION"}:
        return compiled
    if isinstance(column_type, Float):
        precision = column_type.precision
        return "REAL" if precision is not None and precision <= 24 else "DOUBLE PRECISION"
    return compiled


def inspect_compatibility(connection):
    """Return structural failures; never infer ownership or historical values."""
    inspector = inspect(connection)
    problems = []
    tables = set(inspector.get_table_names(schema="public"))
    for name, expected in sorted(Base.metadata.tables.items()):
        # Auth has its own consolidated migration and conditional read-only
        # startup validation in deploy.pilot.runtime. Its natural/composite
        # keys are not Shop's generated business identifiers.
        if name.startswith(("merchant_auth_", "merchant_pin_", "merchant_passkey")):
            continue
        if name not in tables:
            problems.append(f"missing table: public.{name}")
            continue
        columns = {c["name"]: c for c in inspector.get_columns(name, schema="public")}
        for column in expected.columns:
            actual = columns.get(column.name)
            label = f"{name}.{column.name}"
            if actual is None:
                problems.append(f"missing column: {label}")
                continue
            if _type_name(actual["type"], connection.dialect) != _type_name(column.type, connection.dialect):
                problems.append(f"incompatible type: {label}")
            if actual["nullable"] != column.nullable:
                problems.append(f"incompatible nullability: {label}")
            if column.primary_key and column.autoincrement is not False:
                if not actual.get("default") and not actual.get("identity"):
                    problems.append(f"missing generated primary key: {label}")
        if inspector.get_pk_constraint(name, schema="public")["constrained_columns"] != [c.name for c in expected.primary_key.columns]:
            problems.append(f"incompatible primary key: {name}")
        foreign_keys = inspector.get_foreign_keys(name, schema="public")
        for fk in expected.foreign_key_constraints:
            if not any(
                item["constrained_columns"] == [e.parent.name for e in fk.elements]
                and item["referred_table"] == fk.referred_table.name
                and item["referred_columns"] == [e.column.name for e in fk.elements]
                and item["referred_schema"] in (None, "public")
                for item in foreign_keys
            ):
                problems.append(f"missing foreign key: {name}.{','.join(fk.column_keys)}")
        indexes = inspector.get_indexes(name, schema="public")
        uniques = inspector.get_unique_constraints(name, schema="public")
        required = [tuple(c.name for c in u.columns) for u in expected.constraints if isinstance(u, UniqueConstraint)]
        required += [tuple(c.name for c in i.columns) for i in expected.indexes if i.unique]
        for keys in required:
            matched = any(tuple(u["column_names"]) == keys for u in uniques)
            for index in indexes:
                if not index["unique"] or tuple(index["column_names"]) != keys:
                    continue
                predicate = _predicate(index.get("dialect_options", {}).get("postgresql_where"))
                allowed = {""}
                if name == "sales" and keys == ("merchant_id", "sale_number"):
                    allowed.add("merchant_idisnotnullandsale_numberisnotnull")
                if name == "sales" and keys == ("merchant_id", "offline_sale_id"):
                    allowed.add("offline_sale_idisnotnull")
                matched |= predicate in allowed
            if not matched:
                problems.append(f"missing unique key: {name}({','.join(keys)})")
        if name in {"suppliers", "products", "categories"}:
            if any(u["column_names"] == ["name"] for u in uniques) or any(i["unique"] and i["column_names"] == ["name"] for i in indexes):
                problems.append(f"forbidden global name uniqueness: {name}")
    invalid = connection.execute(text("""
        SELECT c.relname FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND (NOT i.indisvalid OR NOT i.indisready)
    """)).scalars().all()
    problems.extend(f"invalid index: {name}" for name in invalid)
    unvalidated = connection.execute(text("""
        SELECT c.conname FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname = 'public' AND NOT c.convalidated
    """)).scalars().all()
    problems.extend(f"unvalidated constraint: {name}" for name in unvalidated)
    if not problems and not connection.execute(text("SELECT 1 FROM public.currencies WHERE code = 'XOF'")).first():
        problems.append("missing reference currency: XOF (explicit seed required)")
    problems.extend(inspect_analytics(connection))
    return problems


def check_schema_compatibility(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        raise SchemaCompatibilityError("Startup compatibility requires PostgreSQL; no automatic bootstrap")
    with engine.connect() as connection:
        # Transaction-scoped: subsequent business requests retain their write permissions.
        with connection.begin():
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            schemas = connection.execute(text("SELECT current_schemas(true)")).scalar_one()
            if set(schemas) != {"pg_catalog", "public"}:
                raise SchemaCompatibilityError("Unsupported search_path; business queries must resolve to public")
            connection.execute(text("SET LOCAL search_path TO public, pg_catalog"))
            connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            connection.execute(text("SET LOCAL lock_timeout = '3s'"))
            if connection.execute(text("SELECT current_schema()")).scalar_one() != "public":
                raise SchemaCompatibilityError("public schema unavailable")
            problems = inspect_compatibility(connection)
            if problems:
                raise SchemaCompatibilityError("Incompatible Shop schema; run the reviewed explicit migration. " + "; ".join(problems))
