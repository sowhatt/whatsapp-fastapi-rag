import os
import time

import jwt
from sqlalchemy.orm import Session

from app.auth import verify_password
from app.models.admin_user import AdminUser


ADMIN_ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ADMIN_TOKEN_TYPE = "admin_access"


class AdminAuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _admin_jwt_secret() -> str:
    secret = os.getenv("ADMIN_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError(
            "ADMIN_JWT_SECRET doit contenir au moins 32 caractères"
        )
    return secret


def authenticate_admin(
    db: Session,
    *,
    email: str,
    password: str,
) -> AdminUser:
    normalized_email = email.strip().lower()

    admin = (
        db.query(AdminUser)
        .filter(AdminUser.email == normalized_email)
        .first()
    )

    if admin is None or not verify_password(password, admin.password_hash):
        raise AdminAuthError(
            "invalid_credentials",
            "Identifiants administrateur invalides",
        )

    if not admin.is_active:
        raise AdminAuthError(
            "admin_inactive",
            "Compte administrateur désactivé",
        )

    if admin.role != ADMIN_ROLE_SUPER_ADMIN:
        raise AdminAuthError(
            "admin_forbidden",
            "Rôle administrateur non autorisé",
        )

    return admin


def create_admin_access_token(admin: AdminUser) -> str:
    now = int(time.time())
    ttl = int(os.getenv("ADMIN_JWT_TTL_SECONDS", "3600"))

    payload = {
        "sub": f"admin:{admin.id}",
        "admin_id": admin.id,
        "role": admin.role,
        "type": ADMIN_TOKEN_TYPE,
        "iat": now,
        "exp": now + ttl,
    }

    return jwt.encode(
        payload,
        _admin_jwt_secret(),
        algorithm="HS256",
    )


def decode_admin_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            _admin_jwt_secret(),
            algorithms=["HS256"],
        )

        if payload.get("type") != ADMIN_TOKEN_TYPE:
            raise ValueError("type de jeton invalide")

        admin_id = int(payload["admin_id"])

        if payload.get("sub") != f"admin:{admin_id}":
            raise ValueError("identité administrateur incohérente")

        if payload.get("role") != ADMIN_ROLE_SUPER_ADMIN:
            raise ValueError("rôle administrateur invalide")

        return payload

    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise AdminAuthError(
            "invalid_admin_token",
            "Jeton administrateur invalide",
        ) from exc


def get_admin_from_token(
    db: Session,
    *,
    token: str,
) -> AdminUser:
    payload = decode_admin_access_token(token)
    admin_id = int(payload["admin_id"])

    admin = (
        db.query(AdminUser)
        .filter(
            AdminUser.id == admin_id,
            AdminUser.is_active.is_(True),
        )
        .first()
    )

    if admin is None:
        raise AdminAuthError(
            "admin_inactive",
            "Administrateur inactif ou introuvable",
        )

    if admin.role != ADMIN_ROLE_SUPER_ADMIN:
        raise AdminAuthError(
            "admin_forbidden",
            "Rôle administrateur non autorisé",
        )

    return admin
