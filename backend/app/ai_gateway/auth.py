"""Machine-to-machine credential parsing; no JWT or MCP privileges."""

import hashlib
import secrets
from fastapi import Header

from app.ai_gateway.errors import GatewayError


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def issue_key():
    raw = "ark_site_" + secrets.token_urlsafe(32)
    return raw, hash_key(raw), raw[:12] + "…" + raw[-4:]


def require_app_key(authorization: str | None = Header(None)) -> str:
    # Machine-to-machine whitelist: grants AI invocation only, never ai:admin.
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw.startswith("ark_site_") or len(raw) > 128:
        raise GatewayError(401, "invalid_api_key", "站点密钥无效")
    return hash_key(raw)
