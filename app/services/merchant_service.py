from sqlalchemy.orm import Session

from app.models.merchant import Merchant


def get_or_create_merchant(
    whatsapp_number: str,
    db: Session,
) -> Merchant:
    normalized = whatsapp_number.strip()

    # Cache strictement limité à la session SQL courante.
    # Le webhook et l'orchestrateur utilisent la même session.
    cache_key = "_whatzabi_current_merchant"
    session_info = getattr(db, "info", None)

    if isinstance(session_info, dict):
        cached = session_info.get(cache_key)
        if (
            cached is not None
            and cached.whatsapp_number == normalized
        ):
            return cached

    merchant = (
        db.query(Merchant)
        .filter(
            Merchant.whatsapp_number == normalized
        )
        .first()
    )

    if merchant is None:
        merchant = Merchant(
            whatsapp_number=normalized,
        )
        db.add(merchant)
        db.commit()
        db.refresh(merchant)

    if isinstance(session_info, dict):
        session_info[cache_key] = merchant

    return merchant

def get_current_shop_name(db: Session, default: str = "Ma boutique") -> str:
    """
    Nom de la boutique du commerçant courant (résolu via
    set_current_merchant en début de traitement), utilisé sur le
    catalogue client et les reçus. Retombe sur `default` si aucun nom
    n'a encore été configuré, plutôt que d'afficher un champ vide.
    """
    from app.db.tenant import get_current_merchant

    merchant_id = get_current_merchant(db)
    if merchant_id is None:
        return default

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if merchant is None or not merchant.shop_name:
        return default

    return merchant.shop_name
