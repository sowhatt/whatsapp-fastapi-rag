from app.models import (  # noqa: F401
    category,
    customer,
    financial_entry,
    merchant,
    payment,
    payment_allocation,
    product,
    purchase,
    purchase_item,
    sale,
    sale_item,
    stock_movement,
    supplier,
    supplier_payment,
    supplier_payment_allocation,
    transaction_event,
)


def with_merchant(db, sender_id: str):
    """
    Résout (ou crée) le commerce du numéro `sender_id` et active le
    filtre multi-tenant sur `db` pour toute donnée créée ensuite dans
    ce test — pour que les fixtures correspondent à ce que
    `process_incoming_message(sender_id=sender_id, ...)` verra
    réellement une fois appelé avec la même session.
    """
    from app.db.tenant import set_current_merchant
    from app.services.merchant_service import get_or_create_merchant

    merchant_obj = get_or_create_merchant(sender_id, db)
    set_current_merchant(db, merchant_obj.id)
    return merchant_obj
