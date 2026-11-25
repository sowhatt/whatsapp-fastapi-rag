"""Émission, échange et révocation des accès commerçant (sans jeton exposé au JavaScript)."""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.merchant.session_models import MerchantLoginLink, MerchantSession
from app.models.merchant import Merchant
from app.services.subscription_access_service import evaluate_subscription_access

COOKIE_NAME = "wz_merchant"
LINK_TTL = timedelta(hours=24)
SESSION_TTL = timedelta(days=14)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue_login_link(*, merchant_id: int, db: Session, created_by: str = "admin") -> tuple[str, datetime]:
    """Retourne (secret, expiration). Le secret n'est jamais stocké ni relisible."""
    secret = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + LINK_TTL
    db.add(MerchantLoginLink(merchant_id=merchant_id, token_hash=_hash(secret), created_by=created_by[:40], expires_at=expires))
    db.commit()
    return secret, expires


def redeem_login_link(*, secret: str, db: Session) -> str | None:
    """Consomme le lien (une seule fois) et ouvre une session ; None si invalide."""
    if not secret or len(secret) > 200:
        return None
    now = datetime.utcnow()
    # UPDATE conditionnel : deux échanges simultanés ne peuvent pas réussir tous les deux.
    claimed = (
        db.query(MerchantLoginLink)
        .filter(MerchantLoginLink.token_hash == _hash(secret), MerchantLoginLink.used_at.is_(None),
                MerchantLoginLink.expires_at > now)
        .update({MerchantLoginLink.used_at: now}, synchronize_session=False)
    )
    if claimed != 1:
        db.rollback()
        return None
    link = db.query(MerchantLoginLink).filter(MerchantLoginLink.token_hash == _hash(secret)).one()
    merchant = db.query(Merchant).filter(Merchant.id == link.merchant_id).first()
    if merchant is None or not evaluate_subscription_access(merchant).allowed:
        db.commit()  # le lien reste consommé
        return None
    session_secret = secrets.token_urlsafe(32)
    db.add(MerchantSession(merchant_id=link.merchant_id, session_hash=_hash(session_secret), expires_at=now + SESSION_TTL))
    db.commit()
    return session_secret


def resolve_session(*, secret: str | None, db: Session) -> MerchantSession | None:
    if not secret or len(secret) > 200:
        return None
    row = db.query(MerchantSession).filter(MerchantSession.session_hash == _hash(secret)).first()
    now = datetime.utcnow()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    merchant = db.query(Merchant).filter(Merchant.id == row.merchant_id).first()
    if merchant is None or not evaluate_subscription_access(merchant).allowed:
        return None
    return row


def revoke_session(*, secret: str | None, db: Session) -> None:
    if not secret:
        return
    row = db.query(MerchantSession).filter(MerchantSession.session_hash == _hash(secret)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()


def revoke_all_sessions(*, merchant_id: int, db: Session) -> int:
    count = (
        db.query(MerchantSession)
        .filter(MerchantSession.merchant_id == merchant_id, MerchantSession.revoked_at.is_(None))
        .update({MerchantSession.revoked_at: datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    return count
