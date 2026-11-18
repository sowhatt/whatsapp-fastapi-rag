"""WebAuthn ceremonies. Public operations own their request DB transaction.

The account row serializes credential use, counters, registration and revocation.
A browser-bound challenge is consumed on verification failure as well as success.
"""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from webauthn import (generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, CredentialDeviceType,
    PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement)

from app.auth import _jwt_secret, create_access_token
from app.models.merchant import Merchant
from app.models.merchant_passkey import (MerchantPasskey as Passkey,
    MerchantPasskeyChallenge as Challenge, MerchantPasskeyRateLimit as RateLimit,
    MerchantPasskeyUser as PasskeyUser)
from app.services import quick_auth_service as quick
from app.services import pilot_auth_service as rollout

CHALLENGE_TTL = timedelta(minutes=3)
MAX_PASSKEYS = 10
ALGORITHMS = [COSEAlgorithmIdentifier.ECDSA_SHA_256, COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256]


@dataclass(frozen=True)
class Configuration:
    rp_id: str
    origin: str


def configuration() -> Configuration:
    if rollout.selected_merchant() is None:
        quick._deny("passkeys_not_configured", 503)
    rp_id = os.getenv("PWA_WEBAUTHN_RP_ID", "")
    origin = os.getenv("PWA_WEBAUTHN_ORIGIN", "")
    try:
        parsed = urlsplit(origin)
        valid = (os.getenv("PWA_WEBAUTHN_ENABLED") == "true"
                 and 0 < len(rp_id) <= 253 and rp_id.isascii()
                 and rp_id == rp_id.lower() and not rp_id.endswith(".")
                 and parsed.scheme == "https" and parsed.hostname == rp_id
                 and not parsed.path and not parsed.query and not parsed.fragment
                 and parsed.username is None and parsed.password is None
                 and parsed.netloc == rp_id + (f":{parsed.port}" if parsed.port else ""))
    except ValueError:
        valid = False
    if not valid:
        quick._deny("passkeys_not_configured", 503)
    return Configuration(rp_id, origin)


def _postgres(db):
    if db.get_bind().dialect.name != "postgresql":
        quick._deny("postgresql_required", 503)


@quick._transaction
def rate_limit(db, *, peer: str, peer_limit: int = 30, peer_window=timedelta(minutes=1)):
    """Global and direct-peer budgets shared by ALL workers; never trust XFF."""
    _postgres(db)
    now = db.scalar(select(func.clock_timestamp()))
    peer_hash = hmac.new(_jwt_secret().encode(), peer.encode(), hashlib.sha256).hexdigest()
    for bucket, limit, window in [("global", 600, timedelta(minutes=1)), (peer_hash, peer_limit, peer_window)]:
        expired = RateLimit.window_started_at <= now - window
        attempts = db.scalar(insert(RateLimit).values(
            bucket=bucket, attempts=1, window_started_at=now).on_conflict_do_update(
                index_elements=[RateLimit.bucket], set_={
                    "attempts": case((expired, 1), else_=RateLimit.attempts + 1),
                    "window_started_at": case((expired, now), else_=RateLimit.window_started_at),
                }).returning(RateLimit.attempts))
        if attempts > limit:
            quick._reject_attempt(db, "attempts_exhausted", 429)


def _account(db, merchant_id, user_id):
    account = db.scalar(select(PasskeyUser).where(
        PasskeyUser.user_id == user_id, PasskeyUser.merchant_id == merchant_id
    ).with_for_update().execution_options(populate_existing=True))
    if account is None:
        quick._deny()
    return account


def _new_challenge(db, config, purpose, *, merchant_id=None, user_id=None, shop_id=None, name=None):
    now = db.scalar(select(func.clock_timestamp()))
    binding = secrets.token_urlsafe(32)
    challenge = Challenge(id=secrets.token_urlsafe(32), challenge=secrets.token_bytes(32),
        binding_hash=quick.token_hash(binding), purpose=purpose, merchant_id=merchant_id,
        user_id=user_id, shop_id=shop_id, name=name, rp_id=config.rp_id, origin=config.origin,
        created_at=now, expires_at=now + CHALLENGE_TTL)
    db.add(challenge)
    db.flush()
    return challenge, binding


def _take_challenge(db, config, challenge_id, binding, purpose):
    challenge = db.scalar(select(Challenge).where(Challenge.id == challenge_id)
                          .with_for_update().execution_options(populate_existing=True))
    now = db.scalar(select(func.clock_timestamp()))
    if (challenge is None or not binding or len(binding) > 128
            or not hmac.compare_digest(challenge.binding_hash, quick.token_hash(binding))
            or challenge.purpose != purpose or challenge.consumed_at is not None):
        quick._deny()
    challenge.consumed_at = now
    if (challenge.expires_at <= now or challenge.created_at > now
            or challenge.created_at + CHALLENGE_TTL <= now
            or challenge.rp_id != config.rp_id or challenge.origin != config.origin):
        quick._reject_attempt(db)
    return challenge, now


def _decode(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid base64url")
    decoded = base64url_to_bytes(value)
    if bytes_to_base64url(decoded) != value:
        raise ValueError("Noncanonical base64url")
    return decoded


def _credential(raw):
    if not isinstance(raw, str) or len(raw) > 65536:
        raise ValueError("Invalid credential")
    credential = json.loads(raw)
    credential_id = _decode(credential["rawId"])
    if not 1 <= len(credential_id) <= 1023 or credential["id"] != credential["rawId"]:
        raise ValueError("Invalid credential ID")
    client = json.loads(_decode(credential["response"]["clientDataJSON"]))
    # The library verifies type/challenge/origin; explicitly disallow iframe ceremonies.
    if client.get("crossOrigin", False) is not False or "topOrigin" in client:
        raise ValueError("Cross-origin ceremony")
    return credential, credential_id


@quick._transaction
def begin_registration(db, *, merchant_id, user_id, shop_id, password, name):
    rollout.require_enabled(merchant_id)
    config = configuration()
    _, now, user, _ = quick._context(db, merchant_id, user_id, shop_id)
    quick._password(db, user, password, now)
    db.execute(insert(PasskeyUser).values(user_id=user_id, merchant_id=merchant_id,
        user_handle=secrets.token_bytes(32)).on_conflict_do_nothing())
    account = _account(db, merchant_id, user_id)
    credentials = list(db.scalars(select(Passkey).where(
        Passkey.user_id == user_id, Passkey.merchant_id == merchant_id,
        Passkey.revoked_at.is_(None))))
    if len(credentials) >= MAX_PASSKEYS:
        quick._reject_attempt(db, "passkey_limit", 409)
    # Only one outstanding registration per account; recovery can invalidate it.
    db.execute(update(Challenge).where(Challenge.user_id == user_id,
        Challenge.merchant_id == merchant_id, Challenge.consumed_at.is_(None)).values(consumed_at=now))
    challenge, binding = _new_challenge(db, config, "register", merchant_id=merchant_id,
        user_id=user_id, shop_id=shop_id, name=name)
    options = generate_registration_options(rp_id=config.rp_id, rp_name="Whatzabi Shop",
        user_id=account.user_handle, user_name=user.full_name, user_display_name=user.full_name,
        challenge=challenge.challenge, timeout=180000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in credentials],
        supported_pub_key_algs=ALGORITHMS)
    return {"challenge_id": challenge.id, "options": json.loads(options_to_json(options)), "binding": binding}


@quick._transaction
def finish_registration(db, *, merchant_id, user_id, shop_id, challenge_id, binding, credential):
    rollout.require_enabled(merchant_id)
    config = configuration()
    _postgres(db)
    _account(db, merchant_id, user_id)
    challenge, now = _take_challenge(db, config, challenge_id, binding, "register")
    try:
        if (challenge.merchant_id, challenge.user_id, challenge.shop_id) != (merchant_id, user_id, shop_id):
            raise ValueError("Wrong account")
        quick._scope(db, merchant_id, user_id, shop_id)
        parsed, _ = _credential(credential)
        verified = verify_registration_response(credential=parsed,
            expected_challenge=challenge.challenge, expected_rp_id=config.rp_id,
            expected_origin=config.origin, require_user_verification=True,
            require_user_presence=True, supported_pub_key_algs=ALGORITHMS)
    except Exception:
        # Do not expose the library's exceptions (they contain client data).
        quick._reject_attempt(db)
    count = db.scalar(select(func.count()).select_from(Passkey).where(
        Passkey.user_id == user_id, Passkey.merchant_id == merchant_id, Passkey.revoked_at.is_(None)))
    if count >= MAX_PASSKEYS:
        quick._reject_attempt(db, "passkey_limit", 409)
    # Global uniqueness includes revoked credentials: never rebind a revoked key.
    new_id = db.scalar(insert(Passkey).values(merchant_id=merchant_id, user_id=user_id,
        credential_id=verified.credential_id, public_key=verified.credential_public_key,
        rp_id=config.rp_id, sign_count=verified.sign_count,
        backup_eligible=verified.credential_device_type == CredentialDeviceType.MULTI_DEVICE,
        backed_up=verified.credential_backed_up, name=challenge.name, shop_id=shop_id, created_at=now
    ).on_conflict_do_nothing(index_elements=[Passkey.credential_id]).returning(Passkey.id))
    if new_id is None:
        quick._reject_attempt(db, "credential_already_registered", 409)
    return {"registered": True, "passkey_id": new_id}


@quick._transaction
def begin_authentication(db):
    config = configuration()
    _postgres(db)
    challenge, binding = _new_challenge(db, config, "authenticate")
    options = generate_authentication_options(rp_id=config.rp_id, challenge=challenge.challenge,
        user_verification=UserVerificationRequirement.REQUIRED, timeout=180000)
    return {"challenge_id": challenge.id, "options": json.loads(options_to_json(options)), "binding": binding}


@quick._transaction
def finish_authentication(db, *, challenge_id, binding, credential):
    config = configuration()
    _postgres(db)
    # Locate the public credential; account identity comes only from the database.
    try:
        parsed, credential_id = _credential(credential)
    except Exception:
        _take_challenge(db, config, challenge_id, binding, "authenticate")
        quick._reject_attempt(db)
    key = db.scalar(select(Passkey).where(Passkey.credential_id == credential_id))
    account = _account(db, key.merchant_id, key.user_id) if key is not None else None
    challenge, now = _take_challenge(db, config, challenge_id, binding, "authenticate")
    try:
        if key is None:
            raise ValueError("Unknown credential")
        db.refresh(key)  # Re-read after the account lock: revocation may have raced us.
        if key.revoked_at is not None or key.rp_id != config.rp_id:
            raise ValueError("Revoked credential")
        if not hmac.compare_digest(_decode(parsed["response"]["userHandle"]), account.user_handle):
            raise ValueError("Wrong user handle")
        rollout.require_enabled(key.merchant_id)
        user, role = quick._scope(db, key.merchant_id, key.user_id, key.shop_id)
        verified = verify_authentication_response(credential=parsed,
            expected_challenge=challenge.challenge, expected_rp_id=config.rp_id,
            expected_origin=config.origin, credential_public_key=key.public_key,
            credential_current_sign_count=key.sign_count, require_user_verification=True)
        if key.backup_eligible != (verified.credential_device_type == CredentialDeviceType.MULTI_DEVICE):
            raise ValueError("Backup eligibility changed")
    except Exception:
        quick._reject_attempt(db)
    key.sign_count = verified.new_sign_count
    key.backed_up = verified.credential_backed_up
    key.last_used_at = now
    merchant = db.get(Merchant, key.merchant_id)
    # Return to the enrolled shop only after revalidating its current membership.
    token = create_access_token(merchant, user_id=user.id, shop_id=key.shop_id, role=role, passkey_id=key.id, auth_time=int(now.timestamp()))
    return {"access_token": token, "token_type": "bearer"}


@quick._transaction
def list_passkeys(db, *, merchant_id, user_id, shop_id):
    configuration()
    quick._scope(db, merchant_id, user_id, shop_id)
    return [{"id": key.id, "name": key.name, "created_at": key.created_at,
             "last_used_at": key.last_used_at, "backed_up": key.backed_up}
        for key in db.scalars(select(Passkey).where(Passkey.merchant_id == merchant_id,
            Passkey.user_id == user_id, Passkey.revoked_at.is_(None)).order_by(Passkey.id))]


@quick._transaction
def revoke(db, *, merchant_id, user_id, shop_id, password, passkey_id=None):
    # Recovery remains possible when the RP configuration is disabled/broken.
    _, now, user, _ = quick._context(db, merchant_id, user_id, shop_id)
    quick._password(db, user, password, now)
    if passkey_id is None:
        # Full loss recovery also retires the S1.5 device reservations/sessions.
        db.execute(update(quick.AuthSession).where(
            quick.AuthSession.merchant_id == merchant_id, quick.AuthSession.user_id == user_id,
            quick.AuthSession.revoked_at.is_(None)).values(is_active=False, revoked_at=now))
        db.execute(update(quick.Device).where(
            quick.Device.merchant_id == merchant_id, quick.Device.user_id == user_id,
            quick.Device.revoked_at.is_(None)).values(is_active=False, revoked_at=now))
    account = db.scalar(select(PasskeyUser).where(PasskeyUser.user_id == user_id,
        PasskeyUser.merchant_id == merchant_id).with_for_update())
    if account is None:
        if passkey_id is not None:
            quick._reject_attempt(db)
        return {"revoked": True}
    query = select(Passkey).where(Passkey.merchant_id == merchant_id, Passkey.user_id == user_id)
    if passkey_id is not None:
        query = query.where(Passkey.id == passkey_id)
    keys = list(db.scalars(query.execution_options(populate_existing=True)))
    if passkey_id is not None and not keys:
        quick._reject_attempt(db)
    for key in keys:
        if key.revoked_at is None:
            key.revoked_at = now
    db.execute(update(Challenge).where(Challenge.merchant_id == merchant_id,
        Challenge.user_id == user_id, Challenge.consumed_at.is_(None)).values(consumed_at=now))
    return {"revoked": True}
