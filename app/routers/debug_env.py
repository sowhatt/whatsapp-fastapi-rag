from fastapi import APIRouter
import os

import os

from fastapi import Header, HTTPException


def _verifier_token_admin(x_admin_token: str) -> None:
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Accès refusé")


router = APIRouter(tags=["debug"])


@router.get("/debug/env")
def debug_env(x_admin_token: str = Header(default="")):
    _verifier_token_admin(x_admin_token)
    whatsapp_keys = sorted([k for k in os.environ.keys() if k.startswith("WHATSAPP")])

    return {
        "has_whatsapp_access_token": bool(os.getenv("WHATSAPP_ACCESS_TOKEN")),
        "has_whatsapp_phone_number_id": bool(os.getenv("WHATSAPP_PHONE_NUMBER_ID")),
        "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID"),
        "whatsapp_keys_seen": whatsapp_keys,
    }