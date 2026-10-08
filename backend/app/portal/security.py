"""Opaque credentials and scoped secrets; never log values returned here."""

import hashlib
import hmac
import re
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.portal.errors import reject


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def keyed_digest(key: str, *parts: str) -> str:
    if len(key.encode("utf-8")) < 32:
        reject("SERVICE_UNAVAILABLE", "Sign-in is temporarily unavailable.", 503)
    # Length prefixes prevent ambiguous input concatenations.
    message = b"".join(len(part.encode()).to_bytes(4, "big") + part.encode() for part in parts)
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def csrf_token(key: str, session_public_id: str, nonce: str) -> str:
    if len(key.encode("utf-8")) < 32:
        reject("SERVICE_UNAVAILABLE", "Sign-in is temporarily unavailable.", 503)
    message = (session_public_id + ":" + nonce).encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def verify_csrf(key: str, session_public_id: str, nonce: str, supplied: str | None):
    expected = csrf_token(key, session_public_id, nonce)
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied) or not hmac.compare_digest(expected, supplied):
        reject("CSRF_REJECTED", "Refresh this page before continuing.", 403)


def require_origin(actual: str | None, expected: str):
    if not actual or actual == "null" or actual != expected:
        reject("CSRF_REJECTED", "This request origin is not allowed.", 403)


def _key(encoded: str) -> bytes:
    try:
        value = bytes.fromhex(encoded)
    except ValueError:
        reject("SERVICE_UNAVAILABLE", "Notification delivery is unavailable.", 503)
    if len(value) != 32:
        reject("SERVICE_UNAVAILABLE", "Notification delivery is unavailable.", 503)
    return value


def seal_secret(key_hex: str, plaintext: str, *, event_key: str, purpose: str, object_id: str) -> bytes:
    nonce = secrets.token_bytes(12)
    aad = f"portal-mail-v1:{event_key}:{purpose}:{object_id}".encode()
    return nonce + AESGCM(_key(key_hex)).encrypt(nonce, plaintext.encode(), aad)


def open_secret(key_hex: str, envelope: bytes, *, event_key: str, purpose: str, object_id: str) -> str:
    aad = f"portal-mail-v1:{event_key}:{purpose}:{object_id}".encode()
    return AESGCM(_key(key_hex)).decrypt(envelope[:12], envelope[12:], aad).decode()
