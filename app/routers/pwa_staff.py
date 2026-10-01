from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import get_current_merchant
from app.models.merchant_user import MerchantUser
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.rbac import require_permission
from app.services.staff_management_service import (
    StaffManagementError,
    create_staff_member,
)


router = APIRouter(prefix="/staff", tags=["pwa-staff"])

PilotStaffRole = Literal["MANAGER", "SELLER"]


class StaffCreatePayload(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    phone_number: str = Field(min_length=5, max_length=30)
    password: str = Field(min_length=8, max_length=200)
    role: PilotStaffRole


class StaffRolePayload(BaseModel):
    role: PilotStaffRole


def _merchant_id(db: Session) -> int:
    merchant_id = get_current_merchant(db)
    if merchant_id is None:
        raise HTTPException(
            status_code=401,
            detail="Contexte commerçant absent.",
        )
    return int(merchant_id)


def _shop_id(db: Session) -> int:
    shop_id = db.info.get("pwa_shop_id")
    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne une boutique avant de gérer l'équipe.",
        )
    return int(shop_id)


def _staff_user(
    db: Session,
    *,
    merchant_id: int,
    user_id: int,
) -> MerchantUser:
    user = (
        db.query(MerchantUser)
        .filter(
            MerchantUser.id == user_id,
            MerchantUser.merchant_id == merchant_id,
        )
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Membre de l'équipe introuvable.",
        )

    return user


def _membership(
    db: Session,
    *,
    user_id: int,
    shop_id: int,
) -> UserShopMembership | None:
    return (
        db.query(UserShopMembership)
        .filter(
            UserShopMembership.user_id == user_id,
            UserShopMembership.shop_id == shop_id,
        )
        .first()
    )


def _phone(
    db: Session,
    *,
    merchant_id: int,
    user_id: int,
    shop_id: int,
) -> UserPhone | None:
    return (
        db.query(UserPhone)
        .filter(
            UserPhone.merchant_id == merchant_id,
            UserPhone.user_id == user_id,
            UserPhone.shop_id == shop_id,
        )
        .first()
    )


def _serialize(
    db: Session,
    *,
    merchant_id: int,
    shop_id: int,
    user: MerchantUser,
) -> dict:
    membership = _membership(
        db,
        user_id=user.id,
        shop_id=shop_id,
    )

    phone = _phone(
        db,
        merchant_id=merchant_id,
        user_id=user.id,
        shop_id=shop_id,
    )

    effective_role = (
        membership.role
        if membership is not None and membership.role
        else user.role
    )

    active = bool(
        user.is_active
        and membership is not None
        and membership.is_active
        and phone is not None
        and phone.is_active
    )

    return {
        "id": user.id,
        "full_name": user.full_name,
        "phone_number": phone.phone_number if phone else None,
        "role": effective_role,
        "is_active": active,
        "shop_id": shop_id,
        "created_at": (
            user.created_at.isoformat()
            if user.created_at
            else None
        ),
    }


@router.get("")
def list_staff(
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("staff.read")),
):
    merchant_id = _merchant_id(db)
    shop_id = _shop_id(db)

    memberships = (
        db.query(UserShopMembership)
        .join(
            MerchantUser,
            MerchantUser.id == UserShopMembership.user_id,
        )
        .filter(
            MerchantUser.merchant_id == merchant_id,
            UserShopMembership.shop_id == shop_id,
        )
        .order_by(MerchantUser.created_at.asc())
        .all()
    )

    rows = []

    for membership in memberships:
        user = _staff_user(
            db,
            merchant_id=merchant_id,
            user_id=membership.user_id,
        )

        rows.append(
            _serialize(
                db,
                merchant_id=merchant_id,
                shop_id=shop_id,
                user=user,
            )
        )

    return rows


@router.post("", status_code=201)
def create_staff(
    payload: StaffCreatePayload,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("staff.manage")),
):
    merchant_id = _merchant_id(db)
    shop_id = _shop_id(db)

    try:
        result = create_staff_member(
            db,
            merchant_id=merchant_id,
            shop_id=shop_id,
            full_name=payload.full_name,
            phone_number=payload.phone_number,
            password=payload.password,
            role=payload.role,
        )

        db.commit()
        db.refresh(result.user)

    except StaffManagementError as exc:
        db.rollback()

        status_code = (
            409
            if exc.code == "phone_already_used"
            else 400
        )

        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        ) from exc

    except Exception:
        db.rollback()
        raise

    return _serialize(
        db,
        merchant_id=merchant_id,
        shop_id=shop_id,
        user=result.user,
    )


@router.patch("/{user_id}/role")
def change_staff_role(
    user_id: int,
    payload: StaffRolePayload,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("staff.manage")),
):
    merchant_id = _merchant_id(db)
    shop_id = _shop_id(db)

    user = _staff_user(
        db,
        merchant_id=merchant_id,
        user_id=user_id,
    )

    if str(user.role).upper() == "OWNER":
        raise HTTPException(
            status_code=400,
            detail="Le rôle du propriétaire ne peut pas être modifié ici.",
        )

    membership = _membership(
        db,
        user_id=user.id,
        shop_id=shop_id,
    )

    if membership is None:
        raise HTTPException(
            status_code=404,
            detail="Ce membre n'est pas affecté à cette boutique.",
        )

    role = payload.role.upper()

    user.role = role
    membership.role = role

    db.commit()
    db.refresh(user)

    return _serialize(
        db,
        merchant_id=merchant_id,
        shop_id=shop_id,
        user=user,
    )


@router.post("/{user_id}/suspend")
def suspend_staff(
    user_id: int,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("staff.manage")),
):
    merchant_id = _merchant_id(db)
    shop_id = _shop_id(db)

    current_user_id = db.info.get("pwa_user_id")

    if current_user_id is not None and int(current_user_id) == user_id:
        raise HTTPException(
            status_code=400,
            detail="Tu ne peux pas suspendre ton propre compte.",
        )

    user = _staff_user(
        db,
        merchant_id=merchant_id,
        user_id=user_id,
    )

    if str(user.role).upper() == "OWNER":
        raise HTTPException(
            status_code=400,
            detail="Le propriétaire ne peut pas être suspendu ici.",
        )

    membership = _membership(
        db,
        user_id=user.id,
        shop_id=shop_id,
    )

    phone = _phone(
        db,
        merchant_id=merchant_id,
        user_id=user.id,
        shop_id=shop_id,
    )

    if membership is None:
        raise HTTPException(
            status_code=404,
            detail="Ce membre n'est pas affecté à cette boutique.",
        )

    user.is_active = False
    membership.is_active = False

    if phone is not None:
        phone.is_active = False

    db.commit()
    db.refresh(user)

    return _serialize(
        db,
        merchant_id=merchant_id,
        shop_id=shop_id,
        user=user,
    )


@router.post("/{user_id}/reactivate")
def reactivate_staff(
    user_id: int,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("staff.manage")),
):
    merchant_id = _merchant_id(db)
    shop_id = _shop_id(db)

    user = _staff_user(
        db,
        merchant_id=merchant_id,
        user_id=user_id,
    )

    if str(user.role).upper() == "OWNER":
        raise HTTPException(
            status_code=400,
            detail="Le propriétaire ne se gère pas depuis cette route.",
        )

    membership = _membership(
        db,
        user_id=user.id,
        shop_id=shop_id,
    )

    phone = _phone(
        db,
        merchant_id=merchant_id,
        user_id=user.id,
        shop_id=shop_id,
    )

    if membership is None or phone is None:
        raise HTTPException(
            status_code=404,
            detail="Affectation ou téléphone du membre introuvable.",
        )

    user.is_active = True
    membership.is_active = True
    phone.is_active = True

    db.commit()
    db.refresh(user)

    return _serialize(
        db,
        merchant_id=merchant_id,
        shop_id=shop_id,
        user=user,
    )
