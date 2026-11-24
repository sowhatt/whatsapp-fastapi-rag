from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.services.merchant_service import (
    normalize_whatsapp_number,
    phone_lookup_candidates,
)


class PilotProvisioningError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PilotProvisioningResult:
    merchant: Merchant
    user: MerchantUser
    shop: Shop
    phone: UserPhone
    membership: UserShopMembership


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _shop_code(name: str) -> str:
    value = re.sub(
        r"[^A-Za-z0-9]+",
        "-",
        name.strip(),
    ).strip("-").upper()

    return (value or "SHOP")[:40]


def create_pilot(
    db: Session,
    *,
    whatsapp_number: str,
    merchant_name: str,
    owner_name: str,
    password: str,
    country_code: str = "BJ",
    currency_code: str = "XOF",
    duration_days: int = 30,
) -> PilotProvisioningResult:
    """
    Provisionne un pilote Whatzabi complet.

    Important :
    - aucune donnée n'est commitée dans cette fonction ;
    - l'appelant contrôle la transaction ;
    - une erreur permet donc un rollback global.
    """

    normalized_phone = normalize_whatsapp_number(
        whatsapp_number
    )

    if not normalized_phone:
        raise PilotProvisioningError(
            "invalid_phone",
            "Le numéro WhatsApp est obligatoire.",
        )

    merchant_name = merchant_name.strip()
    owner_name = owner_name.strip()

    if not merchant_name:
        raise PilotProvisioningError(
            "invalid_merchant_name",
            "Le nom du commerce est obligatoire.",
        )

    if not owner_name:
        raise PilotProvisioningError(
            "invalid_owner_name",
            "Le nom du propriétaire est obligatoire.",
        )

    country_code = country_code.strip().upper()
    currency_code = currency_code.strip().upper()

    if len(country_code) != 2:
        raise PilotProvisioningError(
            "invalid_country_code",
            "Le code pays doit contenir 2 caractères.",
        )

    if len(currency_code) != 3:
        raise PilotProvisioningError(
            "invalid_currency_code",
            "Le code devise doit contenir 3 caractères.",
        )

    if duration_days <= 0:
        raise PilotProvisioningError(
            "invalid_duration",
            "La durée du pilote doit être positive.",
        )

    existing_merchant = (
        db.query(Merchant)
        .filter(
            Merchant.whatsapp_number.in_(
                phone_lookup_candidates(
                    whatsapp_number
                )
            )
        )
        .first()
    )

    if existing_merchant is not None:
        raise PilotProvisioningError(
            "phone_already_registered",
            "Ce numéro est déjà associé à un commerçant.",
        )

    existing_phone = (
        db.query(UserPhone)
        .filter(
            UserPhone.phone_number.in_(
                phone_lookup_candidates(
                    whatsapp_number
                )
            )
        )
        .first()
    )

    if existing_phone is not None:
        raise PilotProvisioningError(
            "phone_already_registered",
            "Ce numéro est déjà associé à un utilisateur.",
        )

    password_hash = hash_password(password)

    now = _utc_now_naive()

    merchant = Merchant(
        whatsapp_number=normalized_phone,
        shop_name=merchant_name,
        country_code=country_code,
        subscription_status="pilot",
        subscription_ends_at=(
            now + timedelta(days=duration_days)
        ),
        password_hash=password_hash,
    )

    db.add(merchant)
    db.flush()

    user = MerchantUser(
        merchant_id=merchant.id,
        full_name=owner_name,
        role="OWNER",
        password_hash=password_hash,
        is_active=True,
    )

    db.add(user)
    db.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name=merchant_name,
        code=_shop_code(merchant_name),
        currency_code=currency_code,
        is_active=True,
    )

    db.add(shop)
    db.flush()

    phone = UserPhone(
        merchant_id=merchant.id,
        user_id=user.id,
        shop_id=shop.id,
        phone_number=normalized_phone,
        is_primary=True,
        is_active=True,
    )

    db.add(phone)

    membership = UserShopMembership(
        user_id=user.id,
        shop_id=shop.id,
        role="OWNER",
        is_active=True,
    )

    db.add(membership)
    db.flush()

    return PilotProvisioningResult(
        merchant=merchant,
        user=user,
        shop=shop,
        phone=phone,
        membership=membership,
    )


def create_pending_pilot(
    db: Session,
    *,
    whatsapp_number: str,
    merchant_name: str,
    owner_name: str,
    country_code: str = "BJ",
    currency_code: str = "XOF",
    duration_days: int = 30,
) -> PilotProvisioningResult:
    """
    Provisionne un pilote sans mot de passe.

    Le compte existe, mais l'OWNER ne peut pas se connecter
    avant d'avoir terminé son activation.
    """

    normalized_phone = normalize_whatsapp_number(whatsapp_number)

    if not normalized_phone:
        raise PilotProvisioningError(
            "invalid_phone",
            "Le numéro WhatsApp est obligatoire.",
        )

    merchant_name = merchant_name.strip()
    owner_name = owner_name.strip()

    if not merchant_name:
        raise PilotProvisioningError(
            "invalid_merchant_name",
            "Le nom du commerce est obligatoire.",
        )

    if not owner_name:
        raise PilotProvisioningError(
            "invalid_owner_name",
            "Le nom du propriétaire est obligatoire.",
        )

    country_code = country_code.strip().upper()
    currency_code = currency_code.strip().upper()

    if len(country_code) != 2:
        raise PilotProvisioningError(
            "invalid_country_code",
            "Le code pays doit contenir 2 caractères.",
        )

    if len(currency_code) != 3:
        raise PilotProvisioningError(
            "invalid_currency_code",
            "Le code devise doit contenir 3 caractères.",
        )

    if duration_days <= 0:
        raise PilotProvisioningError(
            "invalid_duration",
            "La durée du pilote doit être positive.",
        )

    existing_merchant = (
        db.query(Merchant)
        .filter(
            Merchant.whatsapp_number.in_(
                phone_lookup_candidates(whatsapp_number)
            )
        )
        .first()
    )

    if existing_merchant is not None:
        raise PilotProvisioningError(
            "phone_already_registered",
            "Ce numéro est déjà associé à un commerçant.",
        )

    existing_phone = (
        db.query(UserPhone)
        .filter(
            UserPhone.phone_number.in_(
                phone_lookup_candidates(whatsapp_number)
            )
        )
        .first()
    )

    if existing_phone is not None:
        raise PilotProvisioningError(
            "phone_already_registered",
            "Ce numéro est déjà associé à un utilisateur.",
        )

    now = _utc_now_naive()

    merchant = Merchant(
        whatsapp_number=normalized_phone,
        shop_name=merchant_name,
        country_code=country_code,
        subscription_status="pilot",
        subscription_ends_at=now + timedelta(days=duration_days),
        password_hash=None,
    )

    db.add(merchant)
    db.flush()

    user = MerchantUser(
        merchant_id=merchant.id,
        full_name=owner_name,
        role="OWNER",
        password_hash=None,
        is_active=False,
    )

    db.add(user)
    db.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name=merchant_name,
        code=_shop_code(merchant_name),
        currency_code=currency_code,
        is_active=True,
    )

    db.add(shop)
    db.flush()

    phone = UserPhone(
        merchant_id=merchant.id,
        user_id=user.id,
        shop_id=shop.id,
        phone_number=normalized_phone,
        is_primary=True,
        is_active=False,
    )

    db.add(phone)

    membership = UserShopMembership(
        user_id=user.id,
        shop_id=shop.id,
        role="OWNER",
        is_active=False,
    )

    db.add(membership)
    db.flush()

    return PilotProvisioningResult(
        merchant=merchant,
        user=user,
        shop=shop,
        phone=phone,
        membership=membership,
    )
