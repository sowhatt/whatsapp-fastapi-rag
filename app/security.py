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
