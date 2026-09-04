import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership


_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, *, salt: str | None = None) -> str:
    if len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt.encode("utf-8"), n=2**14, r=8, p=1
    ).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, salt, _expected = encoded.split("$", 2)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, encoded)


def _jwt_secret() -> str:
    secret = os.getenv("PWA_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("PWA_JWT_SECRET doit contenir au moins 32 caractères")
    return secret


def create_access_token(
    merchant: Merchant,
    *,
    user_id: int | None = None,
    shop_id: int | None = None,
    role: str | None = None,
) -> str:
    now = int(time.time())
    ttl = int(os.getenv("PWA_JWT_TTL_SECONDS", "3600"))
    payload = {
        "sub": str(merchant.id),
        "merchant_id": merchant.id,
        "iat": now,
        "exp": now + ttl,
        "type": "access",
    }
    if user_id is not None:
        payload["user_id"] = user_id
    if shop_id is not None:
        payload["shop_id"] = shop_id
    if role:
        payload["role"] = role
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _effective_shop_role(
    db: Session,
    *,
    merchant_id: int,
    user: MerchantUser,
    shop_id: int,
) -> str:
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
        raise HTTPException(status_code=403, detail="Boutique non autorisée")

    membership = (
        db.query(UserShopMembership)
        .filter(
            UserShopMembership.user_id == user.id,
            UserShopMembership.shop_id == shop_id,
            UserShopMembership.is_active.is_(True),
        )
        .first()
    )
    if membership is not None:
        return membership.role or user.role

    direct_phone = (
        db.query(UserPhone)
        .filter(
            UserPhone.merchant_id == merchant_id,
            UserPhone.user_id == user.id,
            UserPhone.shop_id == shop_id,
            UserPhone.is_active.is_(True),
        )
        .first()
    )
    if direct_phone is not None:
        return user.role

    raise HTTPException(status_code=403, detail="Boutique non autorisée")


def require_pwa_merchant(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Merchant:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentification requise")
    try:
        payload = jwt.decode(credentials.credentials, _jwt_secret(), algorithms=["HS256"])
        if payload.get("type") != "access":
            raise ValueError("type de jeton invalide")
        merchant_id = int(payload["merchant_id"])
        if payload.get("sub") != str(merchant_id):
            raise ValueError("identité de jeton incohérente")
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Jeton invalide")

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if merchant is None:
        raise HTTPException(status_code=401, detail="Commerçant introuvable")

    user_id = payload.get("user_id")
    shop_id = payload.get("shop_id")
    role = payload.get("role")

    if user_id is not None:
        user = (
            db.query(MerchantUser)
            .filter(
                MerchantUser.id == int(user_id),
                MerchantUser.merchant_id == merchant_id,
                MerchantUser.is_active.is_(True),
            )
            .first()
        )
        if user is None:
            raise HTTPException(status_code=401, detail="Utilisateur inactif ou introuvable")
        user_id = user.id
        role = user.role

        if shop_id is not None:
            shop_id = int(shop_id)
            role = _effective_shop_role(
                db,
                merchant_id=merchant_id,
                user=user,
                shop_id=shop_id,
            )
    elif shop_id is not None:
        raise HTTPException(status_code=401, detail="Contexte boutique invalide")

    set_current_merchant(db, merchant.id)
    db.info["pwa_user_id"] = user_id
    db.info["pwa_shop_id"] = shop_id
    db.info["pwa_role"] = role
    return merchant
