import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.merchant_passkey import MerchantPasskey
from app.models.merchant_auth_device import MerchantAuthDevice
from app.models.merchant_auth_session import MerchantAuthSession
from app.services.pilot_auth_service import QUICK_AUDIENCE, eligible
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.services.subscription_access_service import evaluate_subscription_access


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
    passkey_id: int | None = None,
    auth_expires_at: int | None = None,
    auth_time: int | None = None,
    pin_session_id: int | None = None,
    device_id: int | None = None,
) -> str:
    if pin_session_id is not None and passkey_id is not None:
        raise ValueError("Ambiguous authentication method")
    now = int(time.time())
    ttl = int(os.getenv("PWA_JWT_TTL_SECONDS", "3600"))
    if passkey_id is not None or pin_session_id is not None:
        ttl = min(900, ttl)
    payload = {
        "sub": str(merchant.id),
        "merchant_id": merchant.id,
        "iat": now,
        "exp": min(now + ttl, auth_expires_at or now + ttl),
        "type": "access",
    }
    if user_id is not None:
        payload["user_id"] = user_id
    if shop_id is not None:
        payload["shop_id"] = shop_id
    if role:
        payload["role"] = role
    if passkey_id is not None:
        payload["passkey_id"] = passkey_id
        payload["amr"] = "webauthn"
        if auth_time is not None:
            payload["auth_time"] = auth_time
        payload["exp"] = min(payload["exp"], now + 900, auth_expires_at or now + 900)
    if pin_session_id is not None:
        payload.update(amr="pin", pin_session_id=pin_session_id, device_id=device_id)
    if passkey_id is not None or pin_session_id is not None:
        # The pre-patch server rejects this audience rather than ignoring revocation claims.
        payload["aud"] = QUICK_AUDIENCE
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
        # Legacy password tokens have no audience. New tokens are checked explicitly below.
        payload = jwt.decode(credentials.credentials, _jwt_secret(), algorithms=["HS256"], options={"verify_aud": False})
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

    access = evaluate_subscription_access(merchant)
    if not access.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": access.reason,
                "subscription_status": access.status,
            },
        )

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

    quick_method = payload.get("amr")
    if quick_method in ("pin", "webauthn") or payload.get("aud") is not None:
        if not eligible(merchant_id) or payload.get("aud") != QUICK_AUDIENCE or quick_method not in ("pin", "webauthn"):
            raise HTTPException(status_code=401, detail="Connexion rapide désactivée")

    pin_session_id = payload.get("pin_session_id")
    device_id = payload.get("device_id")
    if quick_method == "pin" or pin_session_id is not None or device_id is not None:
        if (quick_method != "pin" or type(pin_session_id) is not int or type(device_id) is not int
                or user_id is None or shop_id is None or payload.get("passkey_id") is not None):
            raise HTTPException(status_code=401, detail="Session PIN invalide")
        session = db.query(MerchantAuthSession).join(MerchantAuthDevice, MerchantAuthDevice.id == MerchantAuthSession.device_id).filter(
            MerchantAuthSession.id == pin_session_id, MerchantAuthSession.device_id == device_id,
            MerchantAuthSession.merchant_id == merchant_id, MerchantAuthSession.user_id == user_id,
            MerchantAuthSession.purpose == "pin_access", MerchantAuthSession.is_active.is_(True),
            MerchantAuthSession.revoked_at.is_(None), MerchantAuthSession.expires_at > func.clock_timestamp(),
            MerchantAuthSession.created_at <= func.clock_timestamp(),
            MerchantAuthDevice.merchant_id == merchant_id, MerchantAuthDevice.user_id == user_id,
            MerchantAuthDevice.is_active.is_(True), MerchantAuthDevice.revoked_at.is_(None),
            MerchantAuthDevice.origin == os.getenv("PWA_WEBAUTHN_ORIGIN", ""),
            MerchantAuthDevice.public_key.is_not(None)).first()
        if session is None:
            raise HTTPException(status_code=401, detail="Session PIN révoquée ou expirée")

    passkey_id = payload.get("passkey_id")
    if passkey_id is not None or payload.get("amr") == "webauthn":
        if type(passkey_id) is not int or user_id is None or payload.get("amr") != "webauthn":
            raise HTTPException(status_code=401, detail="Jeton Passkey invalide")
        key = db.query(MerchantPasskey).filter(
            MerchantPasskey.id == passkey_id,
            MerchantPasskey.merchant_id == merchant_id,
            MerchantPasskey.user_id == user_id,
            MerchantPasskey.revoked_at.is_(None),
        ).first()
        if key is None:
            raise HTTPException(status_code=401, detail="Passkey révoquée ou introuvable")

    set_current_merchant(db, merchant.id)
    db.info["pwa_user_id"] = user_id
    db.info["pwa_shop_id"] = shop_id
    db.info["pwa_role"] = role
    db.info["pwa_pin_session_id"] = pin_session_id
    db.info["pwa_device_id"] = device_id
    db.info["pwa_passkey_id"] = passkey_id
    db.info["pwa_auth_time"] = payload.get("auth_time")
    db.info["pwa_auth_expires_at"] = payload.get("exp")
    return merchant


def require_pwa_shop(
    merchant: Merchant = Depends(require_pwa_merchant),
    db: Session = Depends(get_db),
) -> Merchant:
    """Quick credentials select a shop; historical token semantics are preserved.

    An older Passkey without an enrolled shop can select/recover through /auth,
    but cannot act as a tenant-wide business credential.
    """
    if (db.info.get("pwa_passkey_id") is not None or db.info.get("pwa_pin_session_id") is not None) and db.info.get("pwa_shop_id") is None:
        raise HTTPException(status_code=409, detail="Sélectionne d’abord une boutique.")
    return merchant
