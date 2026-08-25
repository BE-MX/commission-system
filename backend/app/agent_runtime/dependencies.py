"""Machine authentication for Agent workers and delegated Run callers."""

import hashlib
import hmac
import json

from fastapi import Header, HTTPException

from app.core.config import get_settings


def verify_worker_token(worker_id: str, token: str) -> bool:
    if not worker_id or len(token) < 24:
        return False
    raw = str(get_settings().AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON or "").strip()
    if not raw:
        return False
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(mapping, dict):
        return False
    values = mapping.get(worker_id)
    candidates = values if isinstance(values, list) else [values]
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched = False
    for expected in candidates:
        if isinstance(expected, str) and len(expected) == 64:
            matched = hmac.compare_digest(digest, expected.lower()) or matched
    return matched


def allowed_worker_runtimes(worker_id: str) -> set[str]:
    raw = str(get_settings().AGENT_RUNTIME_WORKER_RUNTIMES_JSON or "").strip()
    try:
        mapping = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return set()
    values = mapping.get(worker_id) if isinstance(mapping, dict) else None
    if not isinstance(values, list):
        return set()
    return {item for item in values if item in {"dsh", "openclaw", "native"}}


def require_agent_worker(
    authorization: str | None = Header(default=None),
    x_agent_worker_id: str | None = Header(default=None),
) -> str:
    """Machine-only dependency; worker ID plus bound bearer token is the credential."""
    scheme, _, token = (authorization or "").partition(" ")
    worker_id = str(x_agent_worker_id or "").strip()
    if scheme.lower() != "bearer" or not verify_worker_token(worker_id, token):
        raise HTTPException(status_code=401, detail="Agent Worker 凭证无效")
    return worker_id
