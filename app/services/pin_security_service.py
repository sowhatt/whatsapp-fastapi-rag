"""Primitives de sécurité PIN pour Whatzabi Auth V2.

Ce module ne délivre aucun accès utilisateur.
L'autorisation de l'appareil, les limitations de tentatives
et les sessions seront contrôlées par le service d'authentification.
"""

import hashlib
import hmac
import os
import re
import secrets


PIN_PATTERN = re.compile(r"^[0-9]{6}$")


def validate_pin(pin: str) -> None:
    if not isinstance(pin, str) or not PIN_PATTERN.fullmatch(pin):
        raise ValueError("Le PIN doit contenir exactement 6 chiffres.")


def _pin_pepper() -> bytes:
    pepper = os.environ.get("PWA_PIN_PEPPER", "")
    if len(pepper) < 32:
        raise RuntimeError(
            "PWA_PIN_PEPPER doit contenir au moins 32 caractères."
        )
    return pepper.encode("utf-8")


def hash_pin(pin: str) -> str:
    validate_pin(pin)

    salt = secrets.token_bytes(16)

    # Le pepper est conservé hors de la base PostgreSQL.
    prepared = hmac.new(
        _pin_pepper(),
        pin.encode("ascii"),
        hashlib.sha256,
    ).digest()

    digest = hashlib.scrypt(
        prepared,
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )

    return f"scrypt-pin-v1${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, encoded: str | None) -> bool:
    if not isinstance(pin, str) or not PIN_PATTERN.fullmatch(pin):
        return False

    if not encoded:
        return False

    try:
        algorithm, salt_hex, digest_hex = encoded.split("$")

        if algorithm != "scrypt-pin-v1":
            return False

        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)

        if len(salt) != 16 or len(expected) != 32:
            return False

        prepared = hmac.new(
            _pin_pepper(),
            pin.encode("ascii"),
            hashlib.sha256,
        ).digest()

        actual = hashlib.scrypt(
            prepared,
            salt=salt,
            n=2**14,
            r=8,
            p=1,
            dklen=32,
        )

        return hmac.compare_digest(actual, expected)

    except (ValueError, TypeError):
        return False
