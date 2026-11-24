import os
import secrets

from fastapi import Header, HTTPException


def require_admin_token(
    x_admin_token: str = Header(
        default="",
        alias="X-Admin-Token",
    ),
) -> None:
    """Protège les routes REST internes et administratives."""
    expected = os.getenv("ADMIN_TOKEN", "")

    if (
        not expected
        or not x_admin_token
        or not secrets.compare_digest(
            x_admin_token,
            expected,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé",
        )


from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.admin_user import AdminUser
from app.services.admin_auth_service import AdminAuthError, get_admin_from_token


_admin_bearer = HTTPBearer(auto_error=False)


def require_admin_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
    db: Session = Depends(get_db),
) -> AdminUser:
    """Authentifie un administrateur Whatzabi via son JWT Admin."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentification administrateur requise",
        )

    try:
        return get_admin_from_token(
            db,
            token=credentials.credentials,
        )
    except AdminAuthError as exc:
        status_code = 403 if exc.code == "admin_forbidden" else 401

        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
            },
        ) from exc
