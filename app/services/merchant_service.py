from datetime import datetime, timezone

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.models.user_phone import UserPhone


ALLOWED_SUBSCRIPTION_STATUSES = {"pilot", "trialing", "active", "grace"}


class MerchantAccessError(Exception):
    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(code)
        self.code = code
        self.user_message = user_message


def normalize_whatsapp_number(value: str) -> str:
    """Normalize real phone numbers while preserving non-phone test/channel IDs."""
    raw = (value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    phone_chars = set("+ -()./")
    looks_like_phone = bool(raw) and all(ch.isdigit() or ch in phone_chars for ch in raw)
    return digits if looks_like_phone and digits else raw


def phone_lookup_candidates(value: str) -> tuple[str, ...]:
    normalized = normalize_whatsapp_number(value)
    candidates = [normalized]
    if normalized.isdigit():
        candidates.append(f"+{normalized}")
    raw = (value or "").strip()
    if raw and raw not in candidates:
        candidates.append(raw)
    return tuple(candidates)


def _assert_subscription(merchant: Merchant) -> None:
    status = str(getattr(merchant, "subscription_status", "") or "").strip().casefold()
    if status not in ALLOWED_SUBSCRIPTION_STATUSES:
        raise MerchantAccessError(
            "inactive_subscription",
            "⛔ Ton abonnement Whatzabi n'est pas actif.\n\nContacte l'administrateur pour régulariser ton abonnement.",
        )

    ends_at = getattr(merchant, "subscription_ends_at", None)
    if ends_at is not None:
        now = datetime.now() if ends_at.tzinfo is None else datetime.now(timezone.utc)
        if ends_at < now:
            raise MerchantAccessError(
                "expired_subscription",
                "⏳ Ton abonnement Whatzabi a expiré.\n\nContacte l'administrateur pour le renouveler.",
            )


def _user_phone_table_available(db: Session) -> bool:
    """Keep legacy/test databases working while the new identity tables roll out."""
    try:
        bind = db.get_bind()
    except (AttributeError, TypeError):
        return False
    try:
        return inspect(bind).has_table(UserPhone.__tablename__)
    except Exception:
        return False


def _find_user_phone(whatsapp_number: str, db: Session):
    if not _user_phone_table_available(db):
        return None
    candidates = phone_lookup_candidates(whatsapp_number)
    return (
        db.query(UserPhone)
        .filter(UserPhone.phone_number.in_(candidates), UserPhone.is_active.is_(True))
        .first()
    )


def resolve_authorized_merchant(whatsapp_number: str, db: Session) -> Merchant:
    """Resolve a known phone identity to its merchant, with legacy fallback."""
    normalized = normalize_whatsapp_number(whatsapp_number)
    candidates = phone_lookup_candidates(whatsapp_number)
    phone = _find_user_phone(whatsapp_number, db)

    merchant = None
    if phone is not None:
        merchant = db.query(Merchant).filter(Merchant.id == phone.merchant_id).first()
        db.info["resolved_user_id"] = phone.user_id
        db.info["resolved_shop_id"] = phone.shop_id
        db.info["resolved_phone_id"] = phone.id
    else:
        merchant = db.query(Merchant).filter(Merchant.whatsapp_number.in_(candidates)).first()

    if merchant is None:
        raise MerchantAccessError(
            "unknown_number",
            "🔒 Ton numéro n'est pas encore activé sur Whatzabi.\n\nContacte l'administrateur pour créer ou activer ton accès.",
        )

    _assert_subscription(merchant)
    db.info["resolved_merchant"] = merchant
    db.info["resolved_merchant_number"] = normalized
    return merchant


def get_or_create_merchant(whatsapp_number: str, db: Session) -> Merchant:
    normalized = normalize_whatsapp_number(whatsapp_number)
    session_info = getattr(db, "info", None)
    if isinstance(session_info, dict):
        authorized = session_info.get("resolved_merchant")
        authorized_number = normalize_whatsapp_number(
            str(session_info.get("resolved_merchant_number") or "")
        )
        if authorized is not None and authorized_number == normalized:
            session_info["_whatzabi_current_merchant"] = authorized
            session_info["_whatzabi_current_merchant_number"] = normalized
            return authorized

        current = session_info.get("_whatzabi_current_merchant")
        current_number = normalize_whatsapp_number(
            str(session_info.get("_whatzabi_current_merchant_number") or "")
        )
        if current is not None and current_number == normalized:
            return current

    merchant = (
        db.query(Merchant)
        .filter(Merchant.whatsapp_number.in_(phone_lookup_candidates(whatsapp_number)))
        .first()
    )
    if merchant is None:
        merchant = Merchant(whatsapp_number=normalized)
        db.add(merchant)
        db.commit()
        db.refresh(merchant)

    if isinstance(session_info, dict):
        session_info["_whatzabi_current_merchant"] = merchant
        session_info["_whatzabi_current_merchant_number"] = normalized
    return merchant


def get_current_shop_name(db: Session, default: str = "Ma boutique") -> str:
    from app.db.tenant import get_current_merchant

    merchant_id = get_current_merchant(db)
    if merchant_id is None:
        return default
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if merchant is None or not merchant.shop_name:
        return default
    return merchant.shop_name
