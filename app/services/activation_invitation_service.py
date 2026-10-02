from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models.activation_invitation import ActivationInvitation
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership


INVITATION_PURPOSE_PILOT_OWNER = "PILOT_OWNER"
INVITATION_PURPOSE_STAFF = "STAFF"


class ActivationInvitationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ActivationInvitationResult:
    invitation: ActivationInvitation
    token: str


@dataclass(frozen=True)
class ActivationResult:
    invitation: ActivationInvitation
    merchant: Merchant
    user: MerchantUser


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_activation_invitation(
    db: Session,
    *,
    merchant: Merchant,
    user: MerchantUser,
    phone_number: str,
    purpose: str,
    expires_in_hours: int = 48,
) -> ActivationInvitationResult:
    if purpose not in {
        INVITATION_PURPOSE_PILOT_OWNER,
        INVITATION_PURPOSE_STAFF,
    }:
        raise ActivationInvitationError(
            "invalid_purpose",
            "Type d'invitation invalide.",
        )

    if user.merchant_id != merchant.id:
        raise ActivationInvitationError(
            "merchant_mismatch",
            "L'utilisateur n'appartient pas à ce commerçant.",
        )

    if expires_in_hours <= 0:
        raise ActivationInvitationError(
            "invalid_expiration",
            "La durée de validité doit être positive.",
        )

    now = _utc_now_naive()

    # Une nouvelle invitation invalide les précédentes invitations
    # encore ouvertes pour le même utilisateur et le même usage.
    previous = (
        db.query(ActivationInvitation)
        .filter(
            ActivationInvitation.merchant_id == merchant.id,
            ActivationInvitation.user_id == user.id,
            ActivationInvitation.purpose == purpose,
            ActivationInvitation.used_at.is_(None),
            ActivationInvitation.revoked_at.is_(None),
        )
        .all()
    )

    for invitation in previous:
        invitation.revoked_at = now

    raw_token = secrets.token_urlsafe(32)

    invitation = ActivationInvitation(
        merchant_id=merchant.id,
        user_id=user.id,
        phone_number=phone_number,
        purpose=purpose,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(hours=expires_in_hours),
    )

    db.add(invitation)
    db.flush()

    return ActivationInvitationResult(
        invitation=invitation,
        token=raw_token,
    )


def get_valid_invitation(
    db: Session,
    *,
    token: str,
    purpose: str | None = None,
) -> ActivationInvitation:
    token = token.strip()

    if not token:
        raise ActivationInvitationError(
            "invalid_token",
            "Invitation invalide.",
        )

    invitation = (
        db.query(ActivationInvitation)
        .filter(
            ActivationInvitation.token_hash == _hash_token(token),
        )
        .first()
    )

    if invitation is None:
        raise ActivationInvitationError(
            "invalid_token",
            "Invitation invalide.",
        )

    if purpose is not None and invitation.purpose != purpose:
        raise ActivationInvitationError(
            "invalid_token",
            "Invitation invalide.",
        )

    if invitation.used_at is not None:
        raise ActivationInvitationError(
            "invitation_used",
            "Cette invitation a déjà été utilisée.",
        )

    if invitation.revoked_at is not None:
        raise ActivationInvitationError(
            "invitation_revoked",
            "Cette invitation n'est plus valide.",
        )

    if invitation.expires_at <= _utc_now_naive():
        raise ActivationInvitationError(
            "invitation_expired",
            "Cette invitation a expiré.",
        )

    return invitation


def activate_invitation(
    db: Session,
    *,
    token: str,
    password: str,
) -> ActivationResult:
    invitation = get_valid_invitation(
        db,
        token=token,
    )

    merchant = (
        db.query(Merchant)
        .filter(Merchant.id == invitation.merchant_id)
        .first()
    )

    user = (
        db.query(MerchantUser)
        .filter(
            MerchantUser.id == invitation.user_id,
            MerchantUser.merchant_id == invitation.merchant_id,
        )
        .first()
    )

    if merchant is None or user is None:
        raise ActivationInvitationError(
            "account_not_found",
            "Compte associé à l'invitation introuvable.",
        )

    password_hash = hash_password(password)

    user.password_hash = password_hash
    user.is_active = True

    phones = (
        db.query(UserPhone)
        .filter(
            UserPhone.merchant_id == invitation.merchant_id,
            UserPhone.user_id == invitation.user_id,
        )
        .all()
    )

    for phone in phones:
        phone.is_active = True

    memberships = (
        db.query(UserShopMembership)
        .filter(
            UserShopMembership.user_id == invitation.user_id,
        )
        .all()
    )

    for membership in memberships:
        membership.is_active = True

    # Compatibilité avec l'ancien login Merchant.
    # Pour un OWNER, on garde les deux hashes synchronisés pendant
    # la transition vers le modèle MerchantUser-only.
    if user.role == "OWNER":
        merchant.password_hash = password_hash

    invitation.used_at = _utc_now_naive()

    db.flush()

    return ActivationResult(
        invitation=invitation,
        merchant=merchant,
        user=user,
    )
