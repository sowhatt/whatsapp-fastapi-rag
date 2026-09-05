from collections.abc import Callable

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "OWNER": frozenset({"*"}),
    "MANAGER": frozenset({
        "sale.create", "sale.cancel", "sale.read", "stock.read", "stock.adjust",
        "product.read", "product.create", "product.update", "customer.read",
        "customer.create", "payment.create", "report.read", "staff.read",
    }),
    "SELLER": frozenset({
        "sale.create", "sale.read", "stock.read", "product.read",
        "customer.read", "customer.create", "payment.create",
    }),
    "STOCK_MANAGER": frozenset({
        "stock.read", "stock.adjust", "product.read", "product.create", "product.update",
    }),
    "ACCOUNTANT": frozenset({
        "sale.read", "stock.read", "product.read", "customer.read", "report.read",
    }),
}


def has_permission(role: str | None, permission: str) -> bool:
    if not role:
        return False
    permissions = ROLE_PERMISSIONS.get(role.upper(), frozenset())
    return "*" in permissions or permission in permissions


def require_permission(permission: str) -> Callable:
    """Require a permission for authenticated PWA staff requests.

    Internal/admin and legacy merchant flows do not carry ``pwa_user_id`` in
    the SQLAlchemy session, so they keep their historical behavior. Staff PWA
    requests are always checked against the effective role resolved from the
    current shop context by ``require_pwa_merchant``.
    """

    def checker(db: Session = Depends(get_db)) -> None:
        user_id = db.info.get("pwa_user_id")
        if user_id is None:
            return

        role = db.info.get("pwa_role")
        if not has_permission(role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission requise : {permission}",
            )

    return checker
