"""Dedicated mailbox worker authentication, isolated from human JWTs."""
import hashlib
import hmac
import json

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def require_mail_worker(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Worker authentication required")
    try:
        configured = json.loads(get_settings().MAIL_OUTREACH_WORKER_TOKENS_JSON)
    except (ValueError, TypeError):
        configured = {}
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    if isinstance(configured, dict):
        for identity, expected in configured.items():
            if (isinstance(identity, str) and 0 < len(identity) <= 64
                    and isinstance(expected, str) and len(expected) == 64
                    and hmac.compare_digest(digest, expected)):
                return identity
    raise HTTPException(401, "Invalid worker credentials")
