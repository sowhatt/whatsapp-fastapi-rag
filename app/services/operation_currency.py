"""Capture the configured operation currency; never backfill or convert history."""
from app.models.shop import Shop
from app.services.shop_context_service import get_current_shop_id
from app.db.tenant import get_current_merchant

def operation_currency(db):
    shop=get_current_shop_id(db)
    if shop is None:return None
    return db.query(Shop.currency_code).filter(Shop.id==shop,Shop.merchant_id==get_current_merchant(db)).scalar()
