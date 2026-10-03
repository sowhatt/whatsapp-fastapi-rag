from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.db.session import get_db
from app.models.activation_invitation import ActivationInvitation
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.services.pilot_provisioning_service import (
    PilotProvisioningError,
    create_pilot,
    create_pending_pilot,
)
from app.services.activation_invitation_service import (
    INVITATION_PURPOSE_PILOT_OWNER,
    ActivationInvitationError,
    create_activation_invitation,
)


router = APIRouter(
    prefix="/admin/pilots",
    tags=["admin-pilots"],
)


class PilotCreatePayload(BaseModel):
    whatsapp_number: str = Field(min_length=5, max_length=30)
    merchant_name: str = Field(min_length=1, max_length=150)
    owner_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=200)
    country_code: str = Field(default="BJ", min_length=2, max_length=2)
    currency_code: str = Field(default="XOF", min_length=3, max_length=3)
    duration_days: int = Field(default=30, ge=1, le=365)


class PilotInvitePayload(BaseModel):
    whatsapp_number: str = Field(min_length=5, max_length=30)
    merchant_name: str = Field(min_length=1, max_length=150)
    owner_name: str = Field(min_length=1, max_length=150)
    country_code: str = Field(default="BJ", min_length=2, max_length=2)
    currency_code: str = Field(default="XOF", min_length=3, max_length=3)
    duration_days: int = Field(default=30, ge=1, le=365)
    invitation_hours: int = Field(default=48, ge=1, le=168)


class PilotExtendPayload(BaseModel):
    days: int = Field(ge=1, le=365)


class PilotResetPasswordPayload(BaseModel):
    password: str = Field(min_length=8, max_length=200)


def _pilot_or_404(
    db: Session,
    merchant_id: int,
) -> Merchant:
    merchant = (
        db.query(Merchant)
        .filter(Merchant.id == merchant_id)
        .first()
    )

    if merchant is None:
        raise HTTPException(
            status_code=404,
            detail="Pilote introuvable",
        )

    return merchant


def _pilot_response(
    db: Session,
    merchant: Merchant,
) -> dict:
    owner = (
        db.query(MerchantUser)
        .filter(
            MerchantUser.merchant_id == merchant.id,
            MerchantUser.role == "OWNER",
        )
        .first()
    )

    shop = (
        db.query(Shop)
        .filter(
            Shop.merchant_id == merchant.id,
        )
        .order_by(Shop.id.asc())
        .first()
    )

    from app.services.pilot_provisioning_service import _utc_now_naive

    now = _utc_now_naive()

    user_count = (
        db.query(MerchantUser)
        .filter(MerchantUser.merchant_id == merchant.id)
        .count()
    )

    invitation = (
        db.query(ActivationInvitation)
        .filter(
            ActivationInvitation.merchant_id == merchant.id,
            ActivationInvitation.purpose == INVITATION_PURPOSE_PILOT_OWNER,
        )
        .order_by(ActivationInvitation.id.desc())
        .first()
    )

    if invitation is None:
        activation = {
            "status": "not_invited",
            "invited_at": None,
            "expires_at": None,
            "activated_at": None,
        }
    else:
        if invitation.used_at is not None:
            activation_status = "activated"
        elif invitation.revoked_at is not None:
            activation_status = "revoked"
        elif invitation.expires_at < now:
            activation_status = "expired"
        else:
            activation_status = "pending"

        activation = {
            "status": activation_status,
            "invited_at": invitation.created_at,
            "expires_at": invitation.expires_at,
            "activated_at": invitation.used_at,
        }

    if merchant.subscription_status == "suspended":
        onboarding_status = "suspended"
    elif (
        merchant.subscription_status in {"expired", "cancelled"}
        or (
            merchant.subscription_ends_at is not None
            and merchant.subscription_ends_at < now
        )
    ):
        onboarding_status = "expired"
    elif owner is None or not owner.is_active:
        onboarding_status = "pending_activation"
    else:
        onboarding_status = "active"

    return {
        "merchant_id": merchant.id,
        "merchant_name": merchant.shop_name,
        "onboarding_status": onboarding_status,
        "created_at": merchant.created_at,
        "user_count": user_count,
        "activation": activation,
        "whatsapp_number": merchant.whatsapp_number,
        "country_code": merchant.country_code,
        "subscription_status": merchant.subscription_status,
        "subscription_ends_at": merchant.subscription_ends_at,
        "owner": {
            "id": owner.id,
            "name": owner.full_name,
            "active": owner.is_active,
        } if owner is not None else None,
        "shop": {
            "id": shop.id,
            "name": shop.name,
            "code": shop.code,
            "currency_code": shop.currency_code,
            "active": shop.is_active,
        } if shop is not None else None,
    }


@router.post("", status_code=201)
def create_pilot_endpoint(
    payload: PilotCreatePayload,
    db: Session = Depends(get_db),
):
    try:
        result = create_pilot(
            db,
            whatsapp_number=payload.whatsapp_number,
            merchant_name=payload.merchant_name,
            owner_name=payload.owner_name,
            password=payload.password,
            country_code=payload.country_code,
            currency_code=payload.currency_code,
            duration_days=payload.duration_days,
        )

        db.commit()

        db.refresh(result.merchant)
        db.refresh(result.user)
        db.refresh(result.shop)

        return _pilot_response(
            db,
            result.merchant,
        )

    except PilotProvisioningError as exc:
        db.rollback()

        status_code = (
            409
            if exc.code == "phone_already_registered"
            else 400
        )

        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    except Exception:
        db.rollback()
        raise


@router.post("/invite", status_code=201)
def invite_pilot(
    payload: PilotInvitePayload,
    db: Session = Depends(get_db),
):
    try:
        result = create_pending_pilot(
            db,
            whatsapp_number=payload.whatsapp_number,
            merchant_name=payload.merchant_name,
            owner_name=payload.owner_name,
            country_code=payload.country_code,
            currency_code=payload.currency_code,
            duration_days=payload.duration_days,
        )

        invitation = create_activation_invitation(
            db,
            merchant=result.merchant,
            user=result.user,
            phone_number=result.phone.phone_number,
            purpose=INVITATION_PURPOSE_PILOT_OWNER,
            expires_in_hours=payload.invitation_hours,
        )

        db.commit()

        db.refresh(result.merchant)
        db.refresh(result.user)
        db.refresh(result.shop)
        db.refresh(invitation.invitation)

        return {
            "pilot": _pilot_response(db, result.merchant),
            "activation": {
                "status": "pending_activation",
                "expires_at": invitation.invitation.expires_at,
                "token": invitation.token,
            },
        }

    except PilotProvisioningError as exc:
        db.rollback()

        status_code = (
            409
            if exc.code == "phone_already_registered"
            else 400
        )

        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    except ActivationInvitationError as exc:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        )

    except Exception:
        db.rollback()
        raise


@router.get("")
def list_pilots(
    db: Session = Depends(get_db),
):
    merchants = (
        db.query(Merchant)
        .filter(
            Merchant.subscription_status.in_(
                (
                    "pilot",
                    "trialing",
                    "active",
                    "grace",
                    "suspended",
                    "expired",
                    "cancelled",
                )
            )
        )
        .order_by(Merchant.id.desc())
        .all()
    )

    return [
        _pilot_response(db, merchant)
        for merchant in merchants
    ]


@router.get("/summary")
def pilots_summary(
    db: Session = Depends(get_db),
):
    from app.services.pilot_provisioning_service import _utc_now_naive

    now = _utc_now_naive()
    expiring_limit = now + timedelta(days=7)

    merchants = (
        db.query(Merchant)
        .filter(
            Merchant.subscription_status.in_(
                (
                    "pilot",
                    "trialing",
                    "active",
                    "grace",
                    "suspended",
                    "expired",
                    "cancelled",
                )
            )
        )
        .all()
    )

    summary = {
        "total": len(merchants),
        "active": 0,
        "pending_activation": 0,
        "suspended": 0,
        "expired": 0,
        "expiring_soon": 0,
    }

    for merchant in merchants:
        owner = (
            db.query(MerchantUser)
            .filter(
                MerchantUser.merchant_id == merchant.id,
                MerchantUser.role == "OWNER",
            )
            .first()
        )

        ends_at = merchant.subscription_ends_at

        if merchant.subscription_status == "suspended":
            summary["suspended"] += 1
            continue

        if (
            merchant.subscription_status in {"expired", "cancelled"}
            or (ends_at is not None and ends_at < now)
        ):
            summary["expired"] += 1
            continue

        if owner is None or not owner.is_active:
            summary["pending_activation"] += 1
            continue

        summary["active"] += 1

        if (
            ends_at is not None
            and now <= ends_at <= expiring_limit
        ):
            summary["expiring_soon"] += 1

    return summary


@router.get("/{merchant_id}")
def get_pilot(
    merchant_id: int,
    db: Session = Depends(get_db),
):
    merchant = _pilot_or_404(
        db,
        merchant_id,
    )

    return _pilot_response(
        db,
        merchant,
    )


@router.post("/{merchant_id}/suspend")
def suspend_pilot(
    merchant_id: int,
    db: Session = Depends(get_db),
):
    merchant = _pilot_or_404(
        db,
        merchant_id,
    )

    merchant.subscription_status = "suspended"

    db.commit()
    db.refresh(merchant)

    return _pilot_response(
        db,
        merchant,
    )


@router.post("/{merchant_id}/reactivate")
def reactivate_pilot(
    merchant_id: int,
    db: Session = Depends(get_db),
):
    merchant = _pilot_or_404(
        db,
        merchant_id,
    )

    merchant.subscription_status = "pilot"

    db.commit()
    db.refresh(merchant)

    return _pilot_response(
        db,
        merchant,
    )


@router.post("/{merchant_id}/extend")
def extend_pilot(
    merchant_id: int,
    payload: PilotExtendPayload,
    db: Session = Depends(get_db),
):
    merchant = _pilot_or_404(
        db,
        merchant_id,
    )

    from app.services.pilot_provisioning_service import (
        _utc_now_naive,
    )

    now = _utc_now_naive()

    base = merchant.subscription_ends_at

    if base is None or base < now:
        base = now

    merchant.subscription_ends_at = (
        base + timedelta(days=payload.days)
    )

    db.commit()
    db.refresh(merchant)

    return _pilot_response(
        db,
        merchant,
    )

@router.post("/{merchant_id}/reset-password")
def reset_pilot_password(
    merchant_id: int,
    payload: PilotResetPasswordPayload,
    db: Session = Depends(get_db),
):
    merchant = _pilot_or_404(
        db,
        merchant_id,
    )

    owner = (
        db.query(MerchantUser)
        .filter(
            MerchantUser.merchant_id == merchant.id,
            MerchantUser.role == "OWNER",
        )
        .first()
    )

    if owner is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "owner_not_found",
                "message": "Propriétaire du pilote introuvable",
            },
        )

    password_hash = hash_password(payload.password)

    owner.password_hash = password_hash
    merchant.password_hash = password_hash

    db.commit()
    db.refresh(merchant)
    db.refresh(owner)

    return {
        "merchant_id": merchant.id,
        "owner_id": owner.id,
        "password_reset": True,
    }

