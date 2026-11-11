"""项目雷达短期签名详情链接。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.core.time import to_beijing_time


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _epoch(now) -> int:
    if now is None:
        return int(time.time())
    return int(to_beijing_time(now).timestamp())


def _signature(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())


def issue_detail_token(secret, user_id, subscription_id, *, now=None, ttl_seconds=86400):
    if not secret:
        raise ValueError("签名密钥未配置")
    payload = _b64(json.dumps({
        "u": int(user_id), "s": int(subscription_id),
        "exp": _epoch(now) + int(ttl_seconds), "scope": "project_radar_detail",
    }, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_signature(secret, payload)}"


def verify_detail_token(secret, token, user_id, subscription_id, *, now=None):
    try:
        if not secret:
            return False
        payload, supplied = str(token).split(".", 1)
        if not hmac.compare_digest(_signature(secret, payload), supplied):
            return False
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return (
            claims.get("scope") == "project_radar_detail"
            and claims.get("u") == int(user_id)
            and claims.get("s") == int(subscription_id)
            and isinstance(claims.get("exp"), int)
            and claims["exp"] >= _epoch(now)
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
        return False
