from sqlalchemy.engine import Engine

from app.db.base import Base
from app.models import (  # noqa: F401 - register every table in Base.metadata
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
    product_image,
    product_publication,
    purchase,
    purchase_item,
    sale,
    sale_item,
    shop,
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
