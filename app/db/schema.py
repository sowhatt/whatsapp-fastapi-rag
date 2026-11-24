from sqlalchemy.engine import Engine

from app.db.base import Base
from app.models import (  # noqa: F401 - register every table in Base.metadata
    activation_invitation,
    admin_user,
    category,
    currency,
    customer,
    exchange_rate,
    financial_entry,
    merchant,
    merchant_user,
    open_tab,
    payment,
    payment_allocation,
    product,
    product_barcode,
    product_image,
    product_publication,
    product_reference,
    purchase,
    purchase_item,
    sale,
    sale_item,
    shop,
    shop_inventory,
    shop_operation,
    stock_movement,
    supplier,
    supplier_payment,
    supplier_payment_allocation,
    transaction_event,
    user_phone,
    user_shop_membership,
)


def create_base_schema(engine: Engine) -> None:
    """Create the current schema before applying legacy compatibility patches."""
    Base.metadata.create_all(engine)


def validate_purchasing_schema(engine: Engine) -> None:
    """Fail before bootstrap writes; never guess or repair a deployed schema.

    Inspector queries are scoped to the connection's default schema. Constraint
    definitions matter, not just names (another schema may use the same names).
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    if not inspector.has_table("suppliers"):
        return  # Empty database: create_all installs the current model.
    message = (
        "Schéma achats/fournisseurs incompatible. Appliquer et contrôler les "
        "migrations explicites avant le démarrage (20261021_purchasing_integrity.sql)."
    )
    if "shop_id" not in {c["name"] for c in inspector.get_columns("suppliers")}:
        raise RuntimeError(message)
    unique = inspector.get_unique_constraints("suppliers")
    indexes = inspector.get_indexes("suppliers")
    if not any(c["column_names"] == ["merchant_id", "shop_id", "name"] for c in unique):
        raise RuntimeError(message)
    for c in unique + [i for i in indexes if i["unique"]]:
        columns = set(c["column_names"])
        predicate = c.get("dialect_options", {}).get("postgresql_where")
        if "name" in columns and columns <= {"merchant_id", "name"} and not predicate:
            raise RuntimeError(message)
    if engine.dialect.name == "postgresql":
        if not any(
            i["unique"] and i["column_names"] == ["merchant_id", "name"]
            and str(i.get("dialect_options", {}).get("postgresql_where", ""))
                .replace("(", "").replace(")", "").strip().lower() == "shop_id is null"
            for i in indexes
        ):
            raise RuntimeError(message)
    if inspector.has_table("purchases") and "initial_paid_amount" not in {
        c["name"] for c in inspector.get_columns("purchases")
    }:
        raise RuntimeError(message)

from app.models import sale_photo_import  # noqa: F401

from app.models import purchasing_receipt  # noqa: F401
