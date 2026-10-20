"""Shared Push subscription boundary, independent of HTTP and auth transport.

The caller must supply a verified backend tenant. SSRF policy remains owned by
push_endpoint; this module neither changes its rules nor sends a notification.
"""
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.notifications.push_endpoint import (
    InvalidPushEndpoint,
    PushPolicyUnavailable,
    validate_push_endpoint,
)
from app.shared.notifications.push_model import WebPushSubscription
from app.shared.tenancy.rls import apply_rls_context


class SubscriptionError(Exception):
    """Safe, structured business error; never carries subscription input."""

    def __init__(self, code: str, status_code: int, message: str):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message


class WebPushKeysPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=10, max_length=255, repr=False)
    auth: str = Field(min_length=5, max_length=255, repr=False)


class WebPushSubscriptionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(repr=False)
    keys: WebPushKeysPayload = Field(repr=False)


def parse_subscription_payload(raw: object) -> WebPushSubscriptionPayload:
    try:
        return WebPushSubscriptionPayload.model_validate(raw)
    except ValueError:
        raise SubscriptionError(
            "invalid_payload", 422, "Souscription Web Push invalide."
        ) from None


def save_subscription(
    *, merchant_id: int, payload: WebPushSubscriptionPayload, db: Session
) -> dict:
    if type(merchant_id) is not int or merchant_id <= 0:
        raise SubscriptionError("invalid_tenant", 403, "Accès commerçant requis.")
    try:
        endpoint = validate_push_endpoint(payload.endpoint).url
    except PushPolicyUnavailable:
        raise SubscriptionError(
            "policy_unavailable", 503, "Configuration Web Push indisponible."
        ) from None
    except InvalidPushEndpoint:
        raise SubscriptionError(
            "invalid_endpoint", 422, "Souscription Web Push invalide."
        ) from None

    apply_rls_context(db, merchant_id=merchant_id)
    row = db.query(WebPushSubscription).filter(
        WebPushSubscription.merchant_id == merchant_id,
        WebPushSubscription.endpoint == endpoint,
    ).first()
    if row is None:
        row = WebPushSubscription(
            merchant_id=merchant_id, endpoint=endpoint,
            p256dh=payload.keys.p256dh, auth=payload.keys.auth, is_active=True,
        )
        db.add(row)
    else:
        row.p256dh = payload.keys.p256dh
        row.auth = payload.keys.auth
        row.is_active = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Global endpoint uniqueness must never rebind another tenant's device.
        raise SubscriptionError(
            "subscription_unavailable", 409,
            "Souscription indisponible pour cette session.",
        ) from None
    apply_rls_context(db, merchant_id=merchant_id)
    db.refresh(row)
    return {"id": row.id, "active": row.is_active}
