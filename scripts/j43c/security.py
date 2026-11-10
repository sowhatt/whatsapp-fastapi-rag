"""Synthetic service identities; independent of Auth V2. No default secret."""
from dataclasses import dataclass
import hashlib
import hmac
import time

from fastapi import HTTPException


@dataclass(frozen=True)
class Principal:
    key_id: str
    secret: bytes
    source: str
    tenant_id: int
    shop_id: int
    device_id: str | None = None

    def authorize(self, payload):
        if (payload["tenant_id"], payload["shop_id"]) != (self.tenant_id, self.shop_id):
            raise HTTPException(403, "SCOPE_DENIED")
        if self.source != "core" and (
            payload["source"] != self.source or payload.get("device_id") != self.device_id
        ):
            raise HTTPException(403, "SOURCE_DENIED")


def signature(secret, path, timestamp, body):
    return hmac.new(secret, b"POST\n" + path.encode() + b"\n" + timestamp.encode() + b"\n" + body,
                    hashlib.sha256).hexdigest()


def signed(principal, path, body, *, timestamp=None):
    stamp = str(int(time.time())) if timestamp is None else str(timestamp)
    return {"X-Key-Id": principal.key_id, "X-Timestamp": stamp,
            "X-Signature": signature(principal.secret, path, stamp, body),
            "Content-Type": "application/json"}


def verify(keys, path, body, headers, *, source=None):
    headers = {key.lower(): value for key, value in headers.items()}
    principal = keys.get(headers.get("x-key-id"))
    stamp = headers.get("x-timestamp", "")
    try:
        fresh = abs(time.time() - int(stamp)) <= 60
    except ValueError:
        fresh = False
    if not principal or not fresh or (source and principal.source != source):
        raise HTTPException(401, "INVALID_SERVICE_IDENTITY")
    expected = signature(principal.secret, path, stamp, body)
    if not hmac.compare_digest(expected, headers.get("x-signature", "")):
        raise HTTPException(401, "INVALID_SIGNATURE")
    return principal
