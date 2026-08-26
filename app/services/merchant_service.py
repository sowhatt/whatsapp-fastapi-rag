from sqlalchemy.orm import Session

from app.models.merchant import Merchant



ALLOWED_SUBSCRIPTION_STATUSES = {
    "pilot",
    "trialing",
    "active",
    "grace",
}


class MerchantAccessError(Exception):
    def __init__(
        self,
        code: str,
        user_message: str,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.user_message = user_message


def resolve_authorized_merchant(
    whatsapp_number: str,
    db: Session,
) -> Merchant:
    """
    Résout un commerçant déjà autorisé.

    Cette fonction ne crée jamais automatiquement de compte.
    Un numéro inconnu ou un abonnement inactif est bloqué avant
    la transcription audio et avant tout appel à l'IA.
    """
    from datetime import datetime, timezone

    normalized = whatsapp_number.strip()

    merchant = (
        db.query(Merchant)
        .filter(Merchant.whatsapp_number == normalized)
        .first()
    )

    if merchant is None:
        raise MerchantAccessError(
            "unknown_number",
            (
                "🔒 Ton numéro n'est pas encore activé sur "
                "Whatzabi.\n\n"
                "Contacte l'administrateur pour créer ou "
                "activer ton commerce."
            ),
        )

    status = str(
        getattr(
            merchant,
            "subscription_status",
            "",
        )
        or ""
    ).strip().casefold()

    if status not in ALLOWED_SUBSCRIPTION_STATUSES:
        raise MerchantAccessError(
            "inactive_subscription",
            (
                "⛔ Ton abonnement Whatzabi n'est pas actif.\n\n"
                "Contacte l'administrateur pour régulariser "
                "ton abonnement."
            ),
        )

    ends_at = getattr(
        merchant,
        "subscription_ends_at",
        None,
    )

    if ends_at is not None:
        # PostgreSQL retourne actuellement un TIMESTAMP sans
        # fuseau. Dans ce cas, on compare deux dates locales
        # naïves. Si une future migration utilise une date avec
        # fuseau, la comparaison est effectuée en UTC.
        if ends_at.tzinfo is None:
            now_for_comparison = datetime.now()
        else:
            now_for_comparison = datetime.now(
                timezone.utc,
            )

        if ends_at < now_for_comparison:
            raise MerchantAccessError(
                "expired_subscription",
                (
                    "⏳ Ton abonnement Whatzabi a expiré.\n\n"
                    "Contacte l'administrateur pour le "
                    "renouveler."
                ),
            )

    # Le cache reste limité à la session SQLAlchemy courante.
    db.info["resolved_merchant"] = merchant
    db.info["resolved_merchant_number"] = normalized

    return merchant


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
