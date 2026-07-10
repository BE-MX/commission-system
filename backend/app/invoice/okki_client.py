"""OKKI open-platform HTTP boundary: token lifecycle + API calls.

Auth is client_credentials (no OKKI account password, no refresh_token):
POST /v1/oauth2/access_token returns an ~8h Bearer token; we cache it in the
ark_xiaoman_settings row (access_token/token_expires_at) and re-fetch before
expiry. api-sandbox.xiaoman.cn IS the production host (official docs).
Business-level mapping stays in xiaoman_service; this module only talks HTTP.

Convention for future OKKI calls (e.g. order push): always go
ensure_access_token → call → on auth failure retry ONCE with force=True,
exactly as get_order_enums does — the recorded expiry is not authoritative
(server may revoke early), the retry is the self-heal path.
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.invoice import xiaoman_service

logger = logging.getLogger(__name__)

TOKEN_SCOPE = "invoices"
REQUEST_TIMEOUT = 60  # 官方文档：连接/响应超时均 60s
# 距过期小于该缓冲即视为失效，提前换新，避免推单途中过期
EXPIRY_BUFFER = timedelta(minutes=5)


class OkkiApiError(ValueError):
    """Raised for credential/HTTP failures; message is safe to show admins."""


def _base_url() -> str:
    return get_settings().OKKI_API_BASE.rstrip("/")


def fetch_token() -> tuple[str, datetime]:
    """Fetch a fresh access token via client_credentials.

    Returns (access_token, expires_at_utc).
    """
    settings = get_settings()
    if not settings.OKKI_CLIENT_ID or not settings.OKKI_CLIENT_SECRET:
        raise OkkiApiError("服务器未配置 OKKI_CLIENT_ID / OKKI_CLIENT_SECRET（backend/.env）")
    try:
        resp = httpx.post(
            f"{_base_url()}/v1/oauth2/access_token",
            json={
                "grant_type": "client_credentials",
                "client_id": settings.OKKI_CLIENT_ID,
                "client_secret": settings.OKKI_CLIENT_SECRET,
                "scope": TOKEN_SCOPE,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning("OKKI token request failed: %s", exc)
        print(f"[okki_client] token request failed: {exc}", flush=True)
        raise OkkiApiError(f"OKKI 鉴权请求失败：{exc}") from exc

    data = _parse_json(resp, context="鉴权")
    token = data.get("access_token")
    if not token:
        # OAuth 错误体形如 {"error": "invalid_client", "error_description": "..."}
        detail = data.get("error_description") or data.get("error") or resp.text[:200]
        logger.warning("OKKI token response without access_token: %s", detail)
        print(f"[okki_client] token response error: {detail}", flush=True)
        raise OkkiApiError(f"OKKI 鉴权失败：{detail}")

    # 文档称 client_credentials 不返回 expires_in（一般 8 小时），实测返回；两头都兜住
    expires_in = int(data.get("expires_in") or 8 * 3600)
    return token, datetime.utcnow() + timedelta(seconds=expires_in)


def ensure_access_token(db: Session, *, force: bool = False) -> str:
    """Return a valid token, fetching + persisting a new one when needed.

    Caller owns the commit (fetch updates the settings row).
    """
    row = xiaoman_service.get_or_create_settings(db)
    if (
        not force
        and row.access_token
        and row.token_expires_at
        and row.token_expires_at - EXPIRY_BUFFER > datetime.utcnow()
    ):
        return row.access_token

    token, expires_at = fetch_token()
    row.access_token = token
    row.token_expires_at = expires_at
    return token


def get_order_enums(db: Session) -> dict:
    """GET /v1/invoices/order/orderEnums — enterprise-specific enum lists.

    Retries once with a forced token refresh on auth failure (token may have
    been revoked server-side before its recorded expiry).
    """
    token = ensure_access_token(db)
    data = _get_json("/v1/invoices/order/orderEnums", token, context="订单枚举")
    if data is None:  # auth failure → one forced refresh
        token = ensure_access_token(db, force=True)
        data = _get_json("/v1/invoices/order/orderEnums", token, context="订单枚举")
        if data is None:
            raise OkkiApiError("OKKI 订单枚举拉取失败：token 刷新后仍被拒绝，请检查凭证与 scope")
    return {
        "order_status_list": data.get("order_status_list") or [],
        "currency_list": data.get("currency_list") or [],
        "price_contract_list": data.get("price_contract_list") or [],
    }


def _get_json(path: str, token: str, *, context: str) -> dict | None:
    """GET with Bearer auth. Returns payload data; None means auth failure
    (caller may retry with a fresh token); other failures raise.
    """
    try:
        resp = httpx.get(
            f"{_base_url()}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning("OKKI GET %s failed: %s", path, exc)
        print(f"[okki_client] GET {path} failed: {exc}", flush=True)
        raise OkkiApiError(f"OKKI {context}请求失败：{exc}") from exc

    if resp.status_code == 401:
        return None
    body = _parse_json(resp, context=context)
    if body.get("error") == "access_denied":
        return None
    if resp.status_code != 200 or (body.get("code") not in (None, 200)):
        detail = body.get("message") or body.get("error_description") or resp.text[:200]
        logger.warning("OKKI GET %s error %s: %s", path, resp.status_code, detail)
        print(f"[okki_client] GET {path} error {resp.status_code}: {detail}", flush=True)
        raise OkkiApiError(f"OKKI {context}失败：{detail}")
    return body.get("data") if isinstance(body.get("data"), dict) else body


def _parse_json(resp: httpx.Response, *, context: str) -> dict:
    try:
        body = resp.json()
    except ValueError as exc:
        logger.warning("OKKI %s non-JSON response (%s): %s", context, resp.status_code, resp.text[:200])
        print(f"[okki_client] {context} non-JSON response {resp.status_code}", flush=True)
        raise OkkiApiError(f"OKKI {context}返回非 JSON（HTTP {resp.status_code}）") from exc
    return body if isinstance(body, dict) else {}
