"""Shared enrollment, PIN budgets and revocation primitives.

Public operations own their transaction and require a dedicated request Session.
Expected credential failures commit attempt counters BEFORE raising HTTPException.
All operations for an account serialize on a PostgreSQL row, including revocation.
"""
from datetime import timedelta
from functools import wraps
import hashlib
import hmac
import secrets

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth import _effective_shop_role, verify_password
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.merchant_auth_attempt import MerchantAuthAttempt as Attempt
from app.models.merchant_auth_device import MerchantAuthDevice as Device
from app.models.merchant_auth_session import MerchantAuthSession as AuthSession
from app.models.merchant_pin_credential import MerchantPinCredential as Credential
from app.services.pin_security_service import _pin_pepper, hash_pin, validate_pin, verify_pin
from app.services.subscription_access_service import evaluate_subscription_access

ENROLLMENT_TTL = timedelta(minutes=5)
ATTEMPT_WINDOW = timedelta(minutes=15)
PIN_LIMIT = 5
ACCOUNT_PIN_LIMIT = 10
PASSWORD_LIMIT = 5


def _configuration():
    try:
        _pin_pepper()
    except RuntimeError:
        _deny("pin_configuration_required", 503)


def _transaction(operation):
    @wraps(operation)
    def run(db, *args, **kwargs):
        try:
            result = operation(db, *args, **kwargs)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
    return run


def _deny(code="authentication_invalid", status=401):
    raise HTTPException(status_code=status, detail={"code": code})


def _reject_attempt(db, code="authentication_invalid", status=401):
    db.commit()  # A request rollback must never erase a failed attempt.
    _deny(code, status)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _scope(db, merchant_id, user_id, shop_id):
    merchant = db.scalar(select(Merchant).where(Merchant.id == merchant_id)
                         .execution_options(populate_existing=True))
    user = db.scalar(select(MerchantUser).where(
        MerchantUser.id == user_id, MerchantUser.merchant_id == merchant_id,
        MerchantUser.is_active.is_(True)).execution_options(populate_existing=True))
    if merchant is None or user is None:
        _deny()
    if not evaluate_subscription_access(merchant).allowed:
        _deny("subscription_inactive", 403)
    role = user.role
    if shop_id is not None:
        role = _effective_shop_role(db, merchant_id=merchant_id, user=user, shop_id=shop_id)
    return user, role


def _context(db, merchant_id, user_id, shop_id):
    if db.get_bind().dialect.name != "postgresql":
        _deny("postgresql_required", 503)
    _scope(db, merchant_id, user_id, shop_id)
    db.execute(insert(Attempt).values(
        merchant_id=merchant_id, user_id=user_id, purpose="pin", attempts=0,
        window_started_at=func.clock_timestamp()).on_conflict_do_nothing())
    budget = db.scalar(select(Attempt).where(
        Attempt.merchant_id == merchant_id, Attempt.user_id == user_id,
        Attempt.purpose == "pin").with_for_update().execution_options(populate_existing=True))
    # Fetch time after acquiring the lock (transaction start time may be stale).
    now = db.scalar(select(func.clock_timestamp()))
    user, role = _scope(db, merchant_id, user_id, shop_id)
    return budget, now, user, role


def _consume(db, budget, now, limit):
    if budget.window_started_at + ATTEMPT_WINDOW <= now:
        budget.attempts = 0
        budget.window_started_at = now
        db.flush()
    if budget.attempts >= limit:
        _reject_attempt(db, "attempts_exhausted", 429)
    # SQL increment under the shared account lock: works across processes/IPs.
    db.execute(update(Attempt).where(
        Attempt.merchant_id == budget.merchant_id, Attempt.user_id == budget.user_id,
        Attempt.purpose == budget.purpose).values(attempts=Attempt.attempts + 1))


def _password(db, user, password, now):
    db.execute(insert(Attempt).values(
        merchant_id=user.merchant_id, user_id=user.id, purpose="password", attempts=0,
        window_started_at=now).on_conflict_do_nothing())
    budget = db.scalar(select(Attempt).where(
        Attempt.merchant_id == user.merchant_id, Attempt.user_id == user.id,
        Attempt.purpose == "password").with_for_update().execution_options(populate_existing=True))
    _consume(db, budget, now, PASSWORD_LIMIT)
    try:
        valid = verify_password(password, user.password_hash)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        _reject_attempt(db)


def _device(db, merchant_id, user_id, device_id):
    device = db.scalar(select(Device).where(
        Device.id == device_id, Device.merchant_id == merchant_id,
        Device.user_id == user_id, Device.is_active.is_(True),
        Device.revoked_at.is_(None)).execution_options(populate_existing=True))
    if device is None:
        _deny()
    return device


def _session(db, merchant_id, user_id, device_id, token, shop_id, now):
    device = _device(db, merchant_id, user_id, device_id)
    if not token or len(token) > 256:
        _deny()
    session = db.scalar(select(AuthSession).where(
        AuthSession.session_token_hash == token_hash(token),
        AuthSession.merchant_id == merchant_id, AuthSession.user_id == user_id,
        AuthSession.device_id == device.id, AuthSession.purpose == "enrollment",
        AuthSession.is_active.is_(True), AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > now).execution_options(populate_existing=True))
    if (session is None or session.shop_id != shop_id or session.created_at > now
            or session.created_at + ENROLLMENT_TTL <= now):
        _deny()
    session.last_used_at = now
    return session


@_transaction
def enroll(db: Session, *, merchant_id: int, user_id: int, shop_id: int | None,
           password: str, device_name: str | None, public_key: bytes | None = None,
           origin: str | None = None):
    _configuration()
    _, now, user, _ = _context(db, merchant_id, user_id, shop_id)
    _password(db, user, password, now)
    if public_key is not None:
        from app.services import pilot_auth_service as rollout, passkey_service
        rollout.require_enabled(merchant_id)
        if origin != passkey_service.configuration().origin or shop_id is None:
            _deny()
    active_count = db.scalar(select(func.count()).select_from(Device).where(
        Device.merchant_id == merchant_id, Device.user_id == user_id,
        Device.is_active.is_(True)))
    if active_count >= 10:
        _reject_attempt(db, "device_limit", 409)
    device = Device(
        merchant_id=merchant_id, user_id=user_id, device_id=secrets.token_urlsafe(32),
        device_name=device_name, public_key=public_key, shop_id=shop_id, origin=origin,
        # Unusable reservation only; this hash is NOT a verified device proof.
        # The random input is discarded and never sent to the client.
        device_secret_hash=token_hash(secrets.token_urlsafe(32)))
    db.add(device)
    db.flush()
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        merchant_id=merchant_id, user_id=user_id, device_id=device.id,
        shop_id=shop_id, purpose="enrollment", session_token_hash=token_hash(token),
        created_at=now, expires_at=now + ENROLLMENT_TTL,
        challenge=secrets.token_bytes(32) if public_key is not None else None)
    db.add(session)
    db.flush()
    result = {"device_id": device.id, "device_handle": device.device_id, "session_token": token,
              "expires_at": session.expires_at, "quick_unlock_enabled": False}
    if public_key is not None:
        from app.services.pin_login_service import encode, message
        result["enrollment_message"] = encode(message(origin, device.device_id, session.challenge, purpose="enroll"))
    return result


@_transaction
def setup_pin(db: Session, *, merchant_id: int, user_id: int, shop_id: int | None,
              device_id: int, token: str, pin: str, confirmation: str, signature: str | None = None):
    _configuration()
    _, now, _, _ = _context(db, merchant_id, user_id, shop_id)
    session = _session(db, merchant_id, user_id, device_id, token, shop_id, now)
    device = _device(db, merchant_id, user_id, device_id)
    try:
        validate_pin(pin)
        validate_pin(confirmation)
    except ValueError:
        _deny("invalid_pin_format", 422)
    if not hmac.compare_digest(pin, confirmation):
        _deny("pin_confirmation_mismatch", 422)
    existing = db.scalar(select(Credential).where(Credential.device_id == device_id))
    if existing is not None:
        _deny("pin_already_configured", 409)
    if device.public_key is not None:
        from app.services.pin_login_service import confirm_enrollment
        confirm_enrollment(db, device, session, signature, now)
    db.add(Credential(merchant_id=merchant_id, user_id=user_id, device_id=device_id,
                      pin_hash=hash_pin(pin)))
    # Single-use enrollment session; PIN setup never grants business access.
    session.is_active = False
    session.revoked_at = now
    return {"configured": True, "quick_unlock_enabled": bool(_device(db, merchant_id, user_id, device_id).public_key)}


@_transaction
def check_pin_component(db: Session, *, merchant_id: int, user_id: int,
                        shop_id: int | None, device_id: int, pin: str) -> bool:
    """Internal component, never an authentication proof on its own."""
    return _check_pin_locked(db, merchant_id=merchant_id, user_id=user_id,
                             shop_id=shop_id, device_id=device_id, pin=pin)


def _check_pin_locked(db, *, merchant_id, user_id, shop_id, device_id, pin):
    """Caller owns the transaction; success must not commit before session issuance."""
    _configuration()
    budget, now, _, _ = _context(db, merchant_id, user_id, shop_id)
    _consume(db, budget, now, ACCOUNT_PIN_LIMIT)
    try:
        _device(db, merchant_id, user_id, device_id)
    except HTTPException:
        _reject_attempt(db)
    credential = db.scalar(select(Credential).where(
        Credential.device_id == device_id, Credential.merchant_id == merchant_id,
        Credential.user_id == user_id).with_for_update().execution_options(populate_existing=True))
    if credential is None:
        _reject_attempt(db)
    if credential.locked_until is not None:
        if credential.locked_until > now:
            _reject_attempt(db, "attempts_exhausted", 429)
        credential.failed_attempts = 0
        credential.locked_until = None
    if not verify_pin(pin, credential.pin_hash):
        db.execute(update(Credential).where(Credential.id == credential.id).values(
            failed_attempts=Credential.failed_attempts + 1, updated_at=now))
        if credential.failed_attempts >= PIN_LIMIT:
            credential.locked_until = now + ATTEMPT_WINDOW
        _reject_attempt(db)
    credential.failed_attempts = 0
    credential.locked_until = None
    return True


@_transaction
def revoke(db: Session, *, merchant_id: int, user_id: int, shop_id: int | None,
           password: str, device_id: int | None = None):
    """Strong reauthentication; device_id=None recovers from loss of ALL devices."""
    _, now, user, _ = _context(db, merchant_id, user_id, shop_id)
    _password(db, user, password, now)
    devices = select(Device.id).where(Device.merchant_id == merchant_id,
                                      Device.user_id == user_id)
    if device_id is not None:
        devices = devices.where(Device.id == device_id)
        if db.scalar(devices) is None:
            _reject_attempt(db)
    ids = list(db.scalars(devices))
    db.execute(update(AuthSession).where(
        AuthSession.merchant_id == merchant_id, AuthSession.user_id == user_id,
        AuthSession.device_id.in_(ids), AuthSession.revoked_at.is_(None)
    ).values(is_active=False, revoked_at=now))
    db.execute(update(Device).where(
        Device.id.in_(ids), Device.revoked_at.is_(None)
    ).values(is_active=False, revoked_at=now))
    return {"revoked": True}


@_transaction
def reset_pin_after_passkey(db, *, merchant_id, user_id, shop_id, passkey_id, device_id, pin, confirmation):
    """Reset this device PIN after a NEW verified UV ceremony.

    The HTTP caller must have consumed a WebAuthn challenge just beforehand.
    This operation revokes sessions and never grants a new access session.
    """
    from app.services import passkey_service as passkeys
    _configuration()
    _, now, _, _ = _context(db, merchant_id, user_id, shop_id)
    passkeys._account(db, merchant_id, user_id)
    key = db.scalar(select(passkeys.Passkey).where(
        passkeys.Passkey.id == passkey_id, passkeys.Passkey.user_id == user_id,
        passkeys.Passkey.merchant_id == merchant_id, passkeys.Passkey.revoked_at.is_(None))
        .execution_options(populate_existing=True))
    if key is None:
        _deny()
    _device(db, merchant_id, user_id, device_id)
    try:
        validate_pin(pin)
        validate_pin(confirmation)
    except ValueError:
        _deny("invalid_pin_format", 422)
    if not hmac.compare_digest(pin, confirmation):
        _deny("pin_confirmation_mismatch", 422)
    credential = db.scalar(select(Credential).where(Credential.device_id == device_id,
        Credential.user_id == user_id, Credential.merchant_id == merchant_id).with_for_update())
    if credential is None:
        _deny()
    credential.pin_hash = hash_pin(pin)
    credential.failed_attempts = 0
    credential.locked_until = None
    credential.updated_at = now
    db.execute(update(AuthSession).where(AuthSession.device_id == device_id,
        AuthSession.user_id == user_id, AuthSession.merchant_id == merchant_id,
        AuthSession.revoked_at.is_(None)).values(is_active=False, revoked_at=now))
    return {"configured": True, "quick_unlock_enabled": bool(_device(db, merchant_id, user_id, device_id).public_key)}
