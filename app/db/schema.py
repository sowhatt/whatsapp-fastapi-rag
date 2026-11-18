from sqlalchemy.engine import Engine

from app.db.base import Base
from app.models import (  # noqa: F401 - register every table in Base.metadata
    activation_invitation,
    admin_user,
    category,
    currency,
    customer,
    customer_refund,
    exchange_rate,
    financial_entry,
    merchant,
    merchant_user,
    open_tab,
    payment,
    payment_allocation,
    payment_request,
    product,
    product_barcode,
    product_image,
    product_publication,
    product_reference,
    purchase,
    purchase_request,
    purchase_item,
    sale,
    sale_item,
    shop,
    shop_inventory,
    shop_operation,
    stock_movement,
    supplier,
    supplier_payment,
    supplier_payment_request,
    supplier_payment_allocation,
    transaction_event,
    user_phone,
    user_shop_membership,
)


def create_base_schema(engine: Engine) -> None:
    """Create the current schema before applying legacy compatibility patches."""
    Base.metadata.create_all(engine, tables=[
        table for table in Base.metadata.sorted_tables
        if not table.name.startswith(("merchant_auth_", "merchant_pin_", "merchant_passkey"))
    ])

from app.models import sale_photo_import  # noqa: F401
