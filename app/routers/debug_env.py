from fastapi import APIRouter
import os

router = APIRouter(tags=["debug"])


@router.get("/debug/env")
def debug_env():
    return {
        "has_whatsapp_access_token": bool(os.getenv("WHATSAPP_ACCESS_TOKEN")),
        "has_whatsapp_phone_number_id": bool(os.getenv("WHATSAPP_PHONE_NUMBER_ID")),
        "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID"),
    }