"""PIN + browser-held P-256 key. All authority comes from persisted account links."""
from datetime import timedelta
import base64
import hmac
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import select, update, delete, func

from app.auth import create_access_token
from app.models.merchant import Merchant
from app.services import quick_auth_service as quick, pilot_auth_service as rollout

TTL = timedelta(minutes=3)


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode(value):
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if encode(raw) != value:
        raise ValueError("noncanonical base64url")
    return raw


def public_key(value):
    try:
        raw = decode(value)
        key = serialization.load_der_public_key(raw)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError("wrong key type")
        return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    except Exception:
        quick._deny("invalid_device_key", 422)


def message(origin, handle, challenge, *, purpose="unlock"):
    # Neither the PIN nor a hash of it is signed: no offline PIN verifier.
    prefix = b"whatzabi-pin-enroll-v1\n" if purpose == "enroll" else b"whatzabi-pin-v1\n"
    return prefix + origin.encode("ascii") + b"\n" + handle.encode("ascii") + b"\n" + challenge


def verify_signature(public, signature, data):
    try:
        raw = decode(signature)
        if len(raw) != 64:
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        serialization.load_der_public_key(public).verify(der, data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError, AttributeError):
        return False


def confirm_enrollment(db, device, session, signature, now):
    from app.services.passkey_service import configuration
    rollout.require_enabled(device.merchant_id)
    origin = configuration().origin
    # A failed proof consumes the enrollment authorization as well.
    session.is_active, session.revoked_at = False, now
    if (not session.challenge or device.origin != origin or not signature
            or not verify_signature(device.public_key, signature,
                message(origin, device.device_id, session.challenge, purpose="enroll"))):
        quick._reject_attempt(db)


@quick._transaction
def begin(db, *, handle, origin):
    rollout.require_enabled()
    device = db.scalar(select(quick.Device).where(quick.Device.device_id == handle))
    if device is None:
        quick._deny()
    rollout.require_enabled(device.merchant_id)
    _, now, _, _ = quick._context(db, device.merchant_id, device.user_id, device.shop_id)
    device = quick._device(db, device.merchant_id, device.user_id, device.id)
    if (not device.public_key or device.shop_id is None or device.origin != origin
            or db.scalar(select(quick.Credential.id).where(quick.Credential.device_id == device.id,
                quick.Credential.merchant_id == device.merchant_id,
                quick.Credential.user_id == device.user_id)) is None):
        quick._deny()
    # Bound challenge storage to one row per device. Never remove access/enrollment rows.
    db.execute(delete(quick.AuthSession).where(quick.AuthSession.device_id == device.id,
        quick.AuthSession.merchant_id == device.merchant_id, quick.AuthSession.user_id == device.user_id,
        quick.AuthSession.purpose == "pin_challenge"))
    binding = secrets.token_urlsafe(32)
    challenge = secrets.token_bytes(32)
    row = quick.AuthSession(merchant_id=device.merchant_id, user_id=device.user_id,
        device_id=device.id, shop_id=device.shop_id, purpose="pin_challenge",
        session_token_hash=quick.token_hash(binding), challenge=challenge,
        created_at=now, expires_at=now + TTL)
    db.add(row)
    db.flush()
    return {"challenge_id": row.id, "message": encode(message(origin, handle, challenge)), "binding": binding}


@quick._transaction
def finish(db, *, challenge_id, binding, signature, pin, origin):
    rollout.require_enabled()
    row = db.get(quick.AuthSession, challenge_id)
    if row is None:
        quick._deny()
    rollout.require_enabled(row.merchant_id)
    budget, now, _, _ = quick._context(db, row.merchant_id, row.user_id, row.shop_id)
    # Same lock order as setup/recovery/revocation: account, then session.
    row = db.scalar(select(quick.AuthSession).where(quick.AuthSession.id == challenge_id)
                    .with_for_update().execution_options(populate_existing=True))
    if (row is None or row.purpose != "pin_challenge" or not row.is_active or row.revoked_at is not None
            or not binding or len(binding) > 128
            or not hmac.compare_digest(row.session_token_hash, quick.token_hash(binding))):
        quick._deny()
    row.is_active = False
    row.revoked_at = now
    if row.expires_at <= now or row.created_at > now or row.created_at + TTL <= now:
        quick._reject_attempt(db)
    device = quick._device(db, row.merchant_id, row.user_id, row.device_id)
    if (device.shop_id != row.shop_id or row.shop_id is None or not row.challenge
            or device.origin != origin or not verify_signature(device.public_key, signature,
                message(origin, device.device_id, row.challenge))):
        quick._consume(db, budget, now, quick.ACCOUNT_PIN_LIMIT)
        quick._reject_attempt(db)
    quick._check_pin_locked(db, merchant_id=row.merchant_id, user_id=row.user_id,
        shop_id=row.shop_id, device_id=row.device_id, pin=pin)
    _, role = quick._scope(db, row.merchant_id, row.user_id, row.shop_id)
    # Bound lifetime; logout/revocation/rollout disable are checked on every use.
    session = quick.AuthSession(merchant_id=row.merchant_id, user_id=row.user_id,
        device_id=row.device_id, shop_id=row.shop_id, purpose="pin_access",
        session_token_hash=quick.token_hash(secrets.token_urlsafe(32)),
        created_at=now, expires_at=now + timedelta(minutes=15))
    db.add(session)
    device.last_used_at = now
    db.flush()
    token = create_access_token(db.get(Merchant, row.merchant_id), user_id=row.user_id,
        shop_id=row.shop_id, role=role, pin_session_id=session.id, device_id=device.id,
        auth_expires_at=int(session.expires_at.timestamp()))
    return {"access_token": token, "token_type": "bearer"}


@quick._transaction
def logout(db, *, merchant_id, user_id, session_id):
    if session_id is not None:
        quick._context(db, merchant_id, user_id, None)
        db.execute(update(quick.AuthSession).where(quick.AuthSession.id == session_id,
            quick.AuthSession.merchant_id == merchant_id, quick.AuthSession.user_id == user_id,
            quick.AuthSession.purpose == "pin_access").values(is_active=False, revoked_at=func.clock_timestamp()))
    return {"logged_out": True}
