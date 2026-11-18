"""Fail-closed rollout of quick authentication to exactly one existing merchant."""
import os
from fastapi import HTTPException

QUICK_AUDIENCE = "whatzabi-quick-v1"


def selected_merchant() -> int | None:
    # One configuration vocabulary. A leftover alternative implementation must not
    # silently select a different account or reopen unrestricted Passkey access.
    if any(name in os.environ for name in (
        "PWA_QUICK_AUTH_PILOT_ENABLED", "PWA_QUICK_AUTH_PILOT_MERCHANT_ID"
    )):
        return None
    value = os.getenv("PWA_QUICK_AUTH_MERCHANT_ID", "")
    if os.getenv("PWA_QUICK_AUTH_ENABLED") != "true" or not value.isascii() or not value.isdigit():
        return None
    return int(value) if int(value) > 0 else None


def eligible(merchant_id: int) -> bool:
    return selected_merchant() == merchant_id


def require_enabled(merchant_id: int | None = None) -> None:
    if selected_merchant() is None or (merchant_id is not None and not eligible(merchant_id)):
        raise HTTPException(403, detail={"code": "quick_auth_disabled"})
