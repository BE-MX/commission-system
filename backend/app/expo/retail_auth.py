"""Narrow bearer grant used only by the retail-mall try-on surface."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import threading
import time

import httpx
from fastapi import Header, HTTPException

from app.core.config import get_settings


_GRANT_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_CACHE_SECONDS = 30
_cache: dict[str, tuple[float, "RetailGrant"]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class RetailGrant:
    token: str
    subject: str
    phone: str
    expires_at: str
    claim_id: str | None = None


def _service_headers(token: str) -> dict[str, str]:
    settings = get_settings()
    secret = settings.EXPO_RETAIL_GRANT_SERVICE_SECRET.strip()
    if not secret:
        raise HTTPException(503, "零售试戴服务密钥未配置")
    return {
        "Authorization": f"TryOn {token}",
        "X-Retail-Tryon-Service": secret,
    }


def _cache_ttl(expires_at: str) -> float:
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return max(0.0, min(float(_CACHE_SECONDS), expiry.timestamp() - time.time()))
    except (TypeError, ValueError):
        return 0.0


def _cached(token: str) -> RetailGrant | None:
    now = time.monotonic()
    with _cache_lock:
        item = _cache.get(token)
        if not item:
            return None
        deadline, grant = item
        if deadline <= now:
            _cache.pop(token, None)
            return None
        return grant


def require_retail_tryon_grant(authorization: str | None = Header(None)) -> RetailGrant:
    """Validate an opaque mall grant without accepting retail cookies in Ark."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "retail" or not _GRANT_RE.fullmatch(token):
        raise HTTPException(401, "零售试戴资格无效")

    cached = _cached(token)
    if cached:
        return cached

    url = get_settings().EXPO_RETAIL_GRANT_INTROSPECTION_URL.strip()
    if not url:
        raise HTTPException(503, "零售试戴资格服务未配置")
    try:
        response = httpx.get(
            url,
            headers=_service_headers(token),
            timeout=8.0,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "零售试戴资格暂时无法核验") from exc
    if response.status_code != 200:
        raise HTTPException(401, "本次免费试戴资格已失效")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(503, "零售试戴资格服务响应异常") from exc
    subject = str(payload.get("subject") or "")
    phone = subject.removeprefix("retail:") if subject.startswith("retail:") else ""
    if payload.get("active") is not True or not re.fullmatch(r"1\d{10}", phone):
        raise HTTPException(401, "零售试戴资格无效")
    grant = RetailGrant(
        token=token,
        subject=subject,
        phone=phone,
        expires_at=str(payload.get("expiresAt") or ""),
        claim_id=str(payload.get("claimId") or "") or None,
    )
    ttl = _cache_ttl(grant.expires_at)
    if ttl <= 0:
        raise HTTPException(401, "本次免费试戴资格已失效")
    with _cache_lock:
        _cache[token] = (time.monotonic() + ttl, grant)
    return grant


def claim_retail_tryon_generation(grant: RetailGrant, claim_id: str) -> None:
    """Atomically bind the mall grant to one Ark session before generation."""
    introspection_url = get_settings().EXPO_RETAIL_GRANT_INTROSPECTION_URL.strip()
    claim_url = introspection_url.rsplit("/", 1)[0] + "/claim"
    try:
        response = httpx.post(
            claim_url,
            headers=_service_headers(grant.token),
            json={"claimId": claim_id},
            timeout=8.0,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "免费试戴资格暂时无法确认，请稍后重试") from exc
    if response.status_code == 409:
        raise HTTPException(409, "本次免费试戴已经生成过效果，如需再次体验请联系专属客服")
    if response.status_code == 401:
        raise HTTPException(401, "本次免费试戴资格已失效")
    if response.status_code != 200:
        raise HTTPException(503, "免费试戴资格暂时无法确认，请稍后重试")
    with _cache_lock:
        _cache.pop(grant.token, None)
