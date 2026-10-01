from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.services.pilot_provisioning_service import (
    PilotProvisioningError,
    create_pilot,
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


class PilotExtendPayload(BaseModel):
    days: int = Field(ge=1, le=365)


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

    return {
        "merchant_id": merchant.id,
        "merchant_name": merchant.shop_name,
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
