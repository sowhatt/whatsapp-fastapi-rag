from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_pwa_merchant
from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.shop import Shop


router = APIRouter(prefix="/settings", tags=["pwa-settings"])


BusinessType = Literal[
    "general_retail",
    "grocery",
    "pharmacy",
    "restaurant_bar",
    "fashion",
    "beauty",
    "hardware",
    "electronics",
    "other",
]


class CommerceSettingsRead(BaseModel):
    shop_name: str | None
    business_type: str
    country_code: str | None
    whatsapp_number: str
    active_shop_id: int
    active_shop_name: str
    active_shop_address: str | None
    currency_code: str
    role: str | None


class CommerceSettingsUpdate(BaseModel):
    shop_name: str = Field(min_length=1, max_length=150)
    business_type: BusinessType
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    active_shop_address: str | None = Field(default=None, max_length=255)


def _active_shop(db: Session, merchant: Merchant) -> Shop:
    shop_id = db.info.get("pwa_shop_id") or db.info.get("resolved_shop_id")

    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne une boutique avant d'ouvrir les paramètres.",
        )

    shop = (
        db.query(Shop)
        .filter(
            Shop.id == int(shop_id),
            Shop.merchant_id == merchant.id,
            Shop.is_active.is_(True),
        )
        .first()
    )

    if shop is None:
        raise HTTPException(
            status_code=404,
            detail="Boutique active introuvable.",
        )

    return shop


def _serialize(
    merchant: Merchant,
    shop: Shop,
    db: Session,
) -> CommerceSettingsRead:
    return CommerceSettingsRead(
        shop_name=merchant.shop_name,
        business_type=merchant.business_type or "general_retail",
        country_code=(merchant.country_code.upper() if merchant.country_code else None),
        whatsapp_number=merchant.whatsapp_number,
        active_shop_id=shop.id,
        active_shop_name=shop.name,
        active_shop_address=shop.address,
        currency_code=shop.currency_code,
        role=db.info.get("pwa_role"),
    )


@router.get("/commerce", response_model=CommerceSettingsRead)
def get_commerce_settings(
    merchant: Merchant = Depends(require_pwa_merchant),
    db: Session = Depends(get_db),
):
    shop = _active_shop(db, merchant)
    return _serialize(merchant, shop, db)


@router.patch("/commerce", response_model=CommerceSettingsRead)
def update_commerce_settings(
    payload: CommerceSettingsUpdate,
    merchant: Merchant = Depends(require_pwa_merchant),
    db: Session = Depends(get_db),
):
    role = str(db.info.get("pwa_role") or "").upper()

    if role not in {"OWNER", "MANAGER"}:
        raise HTTPException(
            status_code=403,
            detail="Seul le propriétaire ou le manager peut modifier les paramètres.",
        )

    shop = _active_shop(db, merchant)

    merchant.shop_name = payload.shop_name.strip()
    merchant.business_type = payload.business_type
    merchant.country_code = (
        payload.country_code.strip().upper()
        if payload.country_code
        else None
    )

    address = (payload.active_shop_address or "").strip()
    shop.address = address or None

    db.commit()
    db.refresh(merchant)
    db.refresh(shop)

    return _serialize(merchant, shop, db)
