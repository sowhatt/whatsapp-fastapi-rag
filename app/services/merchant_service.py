from sqlalchemy.orm import Session

from app.models.merchant import Merchant


def get_or_create_merchant(whatsapp_number: str, db: Session) -> Merchant:
    normalized = whatsapp_number.strip()
    merchant = (
        db.query(Merchant)
        .filter(Merchant.whatsapp_number == normalized)
        .first()
    )
    if merchant:
        return merchant

    merchant = Merchant(whatsapp_number=normalized)
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant
