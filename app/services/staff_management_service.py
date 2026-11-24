from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.services.merchant_service import normalize_whatsapp_number


PILOT_STAFF_ROLES = {"MANAGER", "SELLER"}


class StaffManagementError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class StaffCreationResult:
    user: MerchantUser
    phone: UserPhone
    membership: UserShopMembership
    shop: Shop


def create_staff_member(
    db: Session,
    *,
    merchant_id: int,
    shop_id: int,
    full_name: str,
    phone_number: str,
    password: str,
    role: str,
) -> StaffCreationResult:
    full_name = full_name.strip()
    role = role.strip().upper()

    if not full_name:
        raise StaffManagementError("invalid_name", "Le nom est obligatoire.")

    if role not in PILOT_STAFF_ROLES:
        raise StaffManagementError(
            "invalid_role",
            "Le rôle doit être MANAGER ou SELLER.",
        )

    normalized_phone = normalize_whatsapp_number(phone_number)
    if not normalized_phone:
        raise StaffManagementError(
            "invalid_phone",
            "Le numéro de téléphone est invalide.",
        )

    shop = (
        db.query(Shop)
        .filter(
            Shop.id == shop_id,
            Shop.merchant_id == merchant_id,
            Shop.is_active.is_(True),
        )
        .first()
    )
    if shop is None:
        raise StaffManagementError(
            "shop_not_found",
            "Boutique introuvable ou inactive.",
        )

    duplicate_phone = (
        db.query(UserPhone)
        .filter(UserPhone.phone_number == normalized_phone)
        .first()
    )
    if duplicate_phone is not None:
        raise StaffManagementError(
            "phone_already_used",
            "Ce numéro est déjà utilisé.",
        )

    user = MerchantUser(
        merchant_id=merchant_id,
        full_name=full_name,
        role=role,
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.flush()

    phone = UserPhone(
        merchant_id=merchant_id,
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
        role=role,
        is_active=True,
    )
    db.add(membership)

    db.flush()

    return StaffCreationResult(
        user=user,
        phone=phone,
        membership=membership,
        shop=shop,
    )
