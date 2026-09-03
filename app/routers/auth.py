from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import create_access_token, require_pwa_merchant, verify_password
from app.db.session import get_db
from app.models.merchant import Merchant

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
    return FileResponse(
        PWA_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


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


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    merchant = (
        db.query(Merchant)
        .filter(Merchant.whatsapp_number == payload.whatsapp_number.strip())
        .first()
    )

    if merchant is None or not verify_password(
        payload.password,
        merchant.password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Identifiants invalides",
        )

    return LoginResponse(
        access_token=create_access_token(merchant),
        merchant=MerchantRead(
            id=merchant.id,
            whatsapp_number=merchant.whatsapp_number,
            shop_name=merchant.shop_name,
            subscription_status=merchant.subscription_status,
        ),
    )


@router.get("/me", response_model=MerchantRead)
def me(
    merchant: Merchant = Depends(require_pwa_merchant),
):
    return MerchantRead(
        id=merchant.id,
        whatsapp_number=merchant.whatsapp_number,
        shop_name=merchant.shop_name,
        subscription_status=merchant.subscription_status,
    )
