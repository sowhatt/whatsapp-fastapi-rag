from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import create_access_token, require_pwa_merchant, verify_password
from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
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
    user_name, active_shop_name = _context_names(db, user_id, shop_id)

    return LoginResponse(
        access_token=create_access_token(
            merchant, user_id=user_id, shop_id=shop_id, role=role
        ),
        merchant=MerchantRead(
            id=merchant.id,
            whatsapp_number=payload.whatsapp_number.strip(),
            shop_name=merchant.shop_name,
            subscription_status=merchant.subscription_status,
            user_id=user_id,
            user_name=user_name,
            shop_id=shop_id,
            active_shop_name=active_shop_name,
            role=role,
        ),
    )


@router.get("/me", response_model=MerchantRead)
def me(merchant: Merchant = Depends(require_pwa_merchant), db: Session = Depends(get_db)):
    user_id = db.info.get("pwa_user_id")
    shop_id = db.info.get("pwa_shop_id")
    user_name, active_shop_name = _context_names(db, user_id, shop_id)

    return MerchantRead(
        id=merchant.id,
        whatsapp_number=merchant.whatsapp_number,
        shop_name=merchant.shop_name,
        subscription_status=merchant.subscription_status,
        user_id=user_id,
        user_name=user_name,
        shop_id=shop_id,
        active_shop_name=active_shop_name,
        role=db.info.get("pwa_role"),
    )
