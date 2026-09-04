from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    _effective_shop_role,
    create_access_token,
    require_pwa_merchant,
    verify_password,
)
from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.services.merchant_service import _find_user_phone, phone_lookup_candidates

router = APIRouter(prefix="/auth", tags=["auth"])
PWA_DIR = Path(__file__).resolve().parent.parent / "pwa"


class LoginPayload(BaseModel):
    whatsapp_number: str = Field(min_length=5, max_length=30)
    password: str = Field(min_length=8, max_length=200)


class MerchantRead(BaseModel):
    id: int
    whatsapp_number: str
    shop_name: str | None
    subscription_status: str
    user_id: int | None = None
    user_name: str | None = None
    shop_id: int | None = None
    active_shop_name: str | None = None
    role: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    merchant: MerchantRead


class ShopRead(BaseModel):
    id: int
    name: str
    code: str
    role: str
    is_active: bool


class SelectShopPayload(BaseModel):
    shop_id: int = Field(gt=0)


class SelectShopResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    merchant: MerchantRead


@router.get("/app", include_in_schema=False)
def pwa_app():
    return FileResponse(PWA_DIR / "index.html", media_type="text/html")


@router.get("/styles.css", include_in_schema=False)
def pwa_styles():
    return FileResponse(PWA_DIR / "styles.css", media_type="text/css")


@router.get("/app.js", include_in_schema=False)
def pwa_script():
    return FileResponse(PWA_DIR / "app.js", media_type="application/javascript")


@router.get("/manifest.webmanifest", include_in_schema=False)
def pwa_manifest():
    return FileResponse(PWA_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
def pwa_service_worker():
    return FileResponse(
        PWA_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/auth/"},
    )


@router.get("/icon.svg", include_in_schema=False)
def pwa_icon():
    return FileResponse(PWA_DIR / "icon.svg", media_type="image/svg+xml")


def _context_names(db: Session, user_id: int | None, shop_id: int | None):
    user_name = None
    active_shop_name = None

    if user_id is not None:
        user = db.query(MerchantUser).filter(MerchantUser.id == user_id).first()
        if user is not None:
            user_name = user.full_name

    if shop_id is not None:
        shop = db.query(Shop).filter(Shop.id == shop_id, Shop.is_active.is_(True)).first()
        if shop is not None:
            active_shop_name = shop.name

    return user_name, active_shop_name


def _merchant_read(
    db: Session,
    merchant: Merchant,
    *,
    user_id: int | None,
    shop_id: int | None,
    role: str | None,
    whatsapp_number: str | None = None,
) -> MerchantRead:
    user_name, active_shop_name = _context_names(db, user_id, shop_id)
    return MerchantRead(
        id=merchant.id,
        whatsapp_number=whatsapp_number or merchant.whatsapp_number,
        shop_name=merchant.shop_name,
        subscription_status=merchant.subscription_status,
        user_id=user_id,
        user_name=user_name,
        shop_id=shop_id,
        active_shop_name=active_shop_name,
        role=role,
    )


def _accessible_shops(db: Session, merchant_id: int, user: MerchantUser) -> list[ShopRead]:
    access: dict[int, str] = {}

    memberships = (
        db.query(UserShopMembership, Shop)
        .join(Shop, Shop.id == UserShopMembership.shop_id)
        .filter(
            UserShopMembership.user_id == user.id,
            UserShopMembership.is_active.is_(True),
            Shop.merchant_id == merchant_id,
            Shop.is_active.is_(True),
        )
        .all()
    )
    shops: dict[int, Shop] = {}
    for membership, shop in memberships:
        access[shop.id] = membership.role or user.role
        shops[shop.id] = shop

    direct_shops = (
        db.query(UserPhone, Shop)
        .join(Shop, Shop.id == UserPhone.shop_id)
        .filter(
            UserPhone.merchant_id == merchant_id,
            UserPhone.user_id == user.id,
            UserPhone.is_active.is_(True),
            UserPhone.shop_id.is_not(None),
            Shop.merchant_id == merchant_id,
            Shop.is_active.is_(True),
        )
        .all()
    )
    for _phone, shop in direct_shops:
        shops.setdefault(shop.id, shop)
        access.setdefault(shop.id, user.role)

    return [
        ShopRead(
            id=shop.id,
            name=shop.name,
            code=shop.code,
            role=access[shop.id],
            is_active=shop.is_active,
        )
        for shop in sorted(shops.values(), key=lambda item: (item.name.lower(), item.id))
    ]


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    candidates = phone_lookup_candidates(payload.whatsapp_number)
    phone = _find_user_phone(payload.whatsapp_number, db)

    user = None
    merchant = None
    shop_id = None
    role = None

    if phone is not None:
        user = (
            db.query(MerchantUser)
            .filter(MerchantUser.id == phone.user_id, MerchantUser.is_active.is_(True))
            .first()
        )
        if user is not None:
            merchant = db.query(Merchant).filter(Merchant.id == phone.merchant_id).first()
            shop_id = phone.shop_id
            role = user.role
            valid_password = verify_password(payload.password, user.password_hash)
            if merchant is not None and shop_id is not None:
                role = _effective_shop_role(
                    db,
                    merchant_id=merchant.id,
                    user=user,
                    shop_id=shop_id,
                )
        else:
            valid_password = False
    else:
        merchant = db.query(Merchant).filter(Merchant.whatsapp_number.in_(candidates)).first()
        valid_password = bool(merchant) and verify_password(
            payload.password, merchant.password_hash if merchant else None
        )

    if merchant is None or not valid_password:
        raise HTTPException(status_code=401, detail="Identifiants invalides")

    user_id = user.id if user is not None else None

    return LoginResponse(
        access_token=create_access_token(
            merchant, user_id=user_id, shop_id=shop_id, role=role
        ),
        merchant=_merchant_read(
            db,
            merchant,
            user_id=user_id,
            shop_id=shop_id,
            role=role,
            whatsapp_number=payload.whatsapp_number.strip(),
        ),
    )


@router.get("/me", response_model=MerchantRead)
def me(merchant: Merchant = Depends(require_pwa_merchant), db: Session = Depends(get_db)):
    return _merchant_read(
        db,
        merchant,
        user_id=db.info.get("pwa_user_id"),
        shop_id=db.info.get("pwa_shop_id"),
        role=db.info.get("pwa_role"),
    )


@router.get("/shops", response_model=list[ShopRead])
def list_accessible_shops(
    merchant: Merchant = Depends(require_pwa_merchant),
    db: Session = Depends(get_db),
):
    user_id = db.info.get("pwa_user_id")
    if user_id is None:
        return []

    user = (
        db.query(MerchantUser)
        .filter(
            MerchantUser.id == user_id,
            MerchantUser.merchant_id == merchant.id,
            MerchantUser.is_active.is_(True),
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Utilisateur inactif ou introuvable")
    return _accessible_shops(db, merchant.id, user)


@router.post("/select-shop", response_model=SelectShopResponse)
def select_shop(
    payload: SelectShopPayload,
    merchant: Merchant = Depends(require_pwa_merchant),
    db: Session = Depends(get_db),
):
    user_id = db.info.get("pwa_user_id")
    if user_id is None:
        raise HTTPException(status_code=403, detail="Compte utilisateur requis")

    user = (
        db.query(MerchantUser)
        .filter(
            MerchantUser.id == user_id,
            MerchantUser.merchant_id == merchant.id,
            MerchantUser.is_active.is_(True),
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Utilisateur inactif ou introuvable")

    role = _effective_shop_role(
        db,
        merchant_id=merchant.id,
        user=user,
        shop_id=payload.shop_id,
    )

    return SelectShopResponse(
        access_token=create_access_token(
            merchant,
            user_id=user.id,
            shop_id=payload.shop_id,
            role=role,
        ),
        merchant=_merchant_read(
            db,
            merchant,
            user_id=user.id,
            shop_id=payload.shop_id,
            role=role,
        ),
    )
