from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.db.session import get_db
from app.models.admin_user import AdminUser
from app.security import require_admin_token, require_admin_user
from app.services.admin_auth_service import (
    AdminAuthError,
    authenticate_admin,
    create_admin_access_token,
)


router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


class AdminBootstrapPayload(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=200)


class AdminLoginPayload(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)


class AdminRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminRead


def _admin_read(admin: AdminUser) -> AdminRead:
    return AdminRead(
        id=admin.id,
        email=admin.email,
        full_name=admin.full_name,
        role=admin.role,
        is_active=admin.is_active,
    )


@router.post(
    "/bootstrap",
    response_model=AdminRead,
    status_code=201,
    dependencies=[Depends(require_admin_token)],
)
def bootstrap_admin(
    payload: AdminBootstrapPayload,
    db: Session = Depends(get_db),
):
    """Crée le premier SUPER_ADMIN Whatzabi, une seule fois."""

    if db.query(AdminUser).first() is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "admin_already_initialized",
                "message": "Un administrateur Whatzabi existe déjà",
            },
        )

    admin = AdminUser(
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="SUPER_ADMIN",
        is_active=True,
    )

    db.add(admin)

    try:
        db.commit()
        db.refresh(admin)
    except Exception:
        db.rollback()
        raise

    return _admin_read(admin)


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(
    payload: AdminLoginPayload,
    db: Session = Depends(get_db),
):
    try:
        admin = authenticate_admin(
            db,
            email=payload.email,
            password=payload.password,
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

    return AdminLoginResponse(
        access_token=create_admin_access_token(admin),
        admin=_admin_read(admin),
    )


@router.get("/me", response_model=AdminRead)
def admin_me(
    admin: AdminUser = Depends(require_admin_user),
):
    return _admin_read(admin)
