from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy.orm import Session

from app.shared.tenancy.rls import apply_rls_bypass

from .model import OnlineNotification
from .push_model import WebPushSubscription
from .push_endpoint import (
    InvalidPushEndpoint,
    PinnedPushSession,
    allowed_host_suffixes,
    validate_push_endpoint,
)


def web_push_enabled() -> bool:
    try:
        allowed_host_suffixes()
    except InvalidPushEndpoint:
        return False
    return bool(
        (os.getenv("WEB_PUSH_VAPID_PUBLIC_KEY") or "").strip()
        and (os.getenv("WEB_PUSH_VAPID_PRIVATE_KEY") or "").strip()
        and (os.getenv("WEB_PUSH_VAPID_SUBJECT") or "").strip()
    )


def web_push_public_key() -> str | None:
    value = (os.getenv("WEB_PUSH_VAPID_PUBLIC_KEY") or "").strip()
    return value or None


def _send(subscription_info: dict, payload: dict) -> Any:
    try:
        from pywebpush import webpush
    except ImportError as exc:
        raise RuntimeError("pywebpush is required for Web Push delivery") from exc

    # Re-resolve here and pin the actual connection to a validated address.
    with PinnedPushSession(subscription_info["endpoint"]) as session:
        return webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=(os.getenv("WEB_PUSH_VAPID_PRIVATE_KEY") or "").strip(),
            vapid_claims={
                "sub": (os.getenv("WEB_PUSH_VAPID_SUBJECT") or "").strip(),
            },
            requests_session=session,
            timeout=10,
        )


def dispatch_web_push_for_notification(
    *,
    db: Session,
    notification: OnlineNotification,
    sender=_send,
) -> dict:
    if notification.recipient_role != "merchant":
        return {"attempted": 0, "sent": 0, "failed": 0}
    apply_rls_bypass(db, enabled=True)
    subscriptions = (
        db.query(WebPushSubscription)
        .filter(
            WebPushSubscription.merchant_id == notification.merchant_id,
            WebPushSubscription.is_active.is_(True),
        )
        .all()
    )

    sent = 0
    failed = 0
    attempted = 0
    disabled = False
    payload = {
        "title": notification.title,
        "body": notification.body,
        "url": notification.action_url or "/online-admin-ui",
        "notification_id": notification.id,
    }

    for subscription in subscriptions:
        try:
            validate_push_endpoint(subscription.endpoint)
            if not web_push_enabled():
                continue
            attempted += 1
            sender(
                {
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                payload,
            )
            sent += 1
        except InvalidPushEndpoint:
            subscription.is_active = False
            disabled = True
            failed += 1
        except Exception:
            failed += 1

    if disabled:
        db.commit()

    return {
        "attempted": attempted,
        "sent": sent,
        "failed": failed,
    }
