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


_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, *, salt: str | None = None) -> str:
    if len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caractères")

    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=2**14,
        r=8,
        p=1,
    ).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False

    try:
        algorithm, salt, expected = encoded.split("$", 2)
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


def create_access_token(merchant: Merchant) -> str:
    now = int(time.time())
    ttl = int(os.getenv("PWA_JWT_TTL_SECONDS", "3600"))

    return jwt.encode(
        {
            "sub": str(merchant.id),
            "merchant_id": merchant.id,
            "iat": now,
            "exp": now + ttl,
            "type": "access",
        },
        _jwt_secret(),
        algorithm="HS256",
    )


def require_pwa_merchant(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Merchant:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentification requise")

    try:
        payload = jwt.decode(
            credentials.credentials,
            _jwt_secret(),
            algorithms=["HS256"],
        )
        if payload.get("type") != "access":
            raise ValueError("type de jeton invalide")
        if payload.get("type") != "access":
            raise ValueError("type de jeton invalide")
        merchant_id = int(payload["merchant_id"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Jeton invalide")

    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()

    if merchant is None:
        raise HTTPException(status_code=401, detail="Commerçant introuvable")

    set_current_merchant(db, merchant.id)
    return merchant
