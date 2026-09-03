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
from app.core.time import utc_now_naive

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.invoice import xiaoman_service

logger = logging.getLogger(__name__)

# scope 半角空格分隔（官方鉴权文档 api-3473041）：
# invoices=订单推送；company=客户查询/详情（发票录入页手动同步客户用）。
# OKKI 后台「企业管理 → 外部对接 → API对接」需给应用开通对应模块，否则 401/access_denied
TOKEN_SCOPE = "invoices company"
REQUEST_TIMEOUT = 60  # 官方文档：连接/响应超时均 60s
# 距过期小于该缓冲即视为失效，提前换新，避免推单途中过期
EXPIRY_BUFFER = timedelta(minutes=5)


class OkkiApiError(ValueError):
    """Raised for credential/HTTP failures; message is safe to show admins."""


class OkkiOutcomeUncertainError(OkkiApiError):
    """The request may have been accepted, so automatically retrying could duplicate it."""


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
    return token, utc_now_naive() + timedelta(seconds=expires_in)


def ensure_access_token(db: Session, *, force: bool = False) -> str:
    """Return a valid token, fetching + persisting a new one when needed.

    Caller owns the commit (fetch updates the settings row).
    """
    row = xiaoman_service.get_or_create_settings(db)
    if (
        not force
        and row.access_token
        and row.token_expires_at
        and row.token_expires_at - EXPIRY_BUFFER > utc_now_naive()
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


def push_order(db: Session, payload: dict) -> dict:
    """POST /v1/invoices/order/push — create or edit (payload carries order_id).

    NO SANDBOX: this creates/edits a REAL order in OKKI. Retries once with a
    forced token refresh on auth failure, same as get_order_enums.
    """
    token = ensure_access_token(db)
    data = _post_json("/v1/invoices/order/push", token, payload, context="订单推送")
    if data is None:  # auth failure → one forced refresh
        token = ensure_access_token(db, force=True)
        data = _post_json("/v1/invoices/order/push", token, payload, context="订单推送")
        if data is None:
            raise OkkiApiError("OKKI 订单推送失败：token 刷新后仍被拒绝，请检查凭证与 scope")
    return data


def query_companies_by_name(db: Session, word: str, *, count: int = 20) -> list[dict]:
    """GET /v1/company/query — 客户查重（search_field=name：公司名/简称模糊）。

    只读接口（company scope），手动同步客户用。
    返回 [{company_id, name, short_name, serial_id, is_public}, ...]。
    """
    params = {"word": word, "search_field": "name", "count": count}
    token = ensure_access_token(db)
    data = _get_json("/v1/company/query", token, context="客户查询", params=params)
    if data is None:  # auth failure → one forced refresh
        token = ensure_access_token(db, force=True)
        data = _get_json("/v1/company/query", token, context="客户查询", params=params)
        if data is None:
            raise OkkiApiError("OKKI 客户查询失败：token 刷新后仍被拒绝，请检查凭证与 scope（客户接口需开通 company 模块）")
    items = (data or {}).get("list") or []
    return items if isinstance(items, list) else []


def get_company_info(db: Session, company_id: int) -> dict:
    """GET /v1/company/info — 客户详情（含 owner 跟进人列表）。只读接口（company scope）。"""
    params = {"company_id": company_id}
    token = ensure_access_token(db)
    data = _get_json("/v1/company/info", token, context="客户详情", params=params)
    if data is None:  # auth failure → one forced refresh
        token = ensure_access_token(db, force=True)
        data = _get_json("/v1/company/info", token, context="客户详情", params=params)
        if data is None:
            raise OkkiApiError("OKKI 客户详情拉取失败：token 刷新后仍被拒绝，请检查凭证与 scope（客户接口需开通 company 模块）")
    return data or {}


def _post_json(path: str, token: str, payload: dict, *, context: str) -> dict | None:
    """POST with Bearer auth. Returns payload data; None means auth failure
    (caller may retry with a fresh token); other failures raise.
    """
    try:
        resp = httpx.post(
            f"{_base_url()}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.TimeoutException as exc:
        # 超时时 OKKI 可能已受理：盲目重试会建出第二张真实订单
        logger.warning("OKKI POST %s timeout: %s", path, exc)
        print(f"[okki_client] POST {path} timeout: {exc}", flush=True)
        raise OkkiOutcomeUncertainError(
            f"OKKI {context}请求超时：订单可能已在 OKKI 生成，请先到 OKKI 后台确认，禁止直接重试"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("OKKI POST %s failed: %s", path, exc)
        print(f"[okki_client] POST {path} failed: {exc}", flush=True)
        raise OkkiOutcomeUncertainError(
            f"OKKI {context}请求连接中断：订单可能已被受理，请先到 OKKI 后台确认，禁止直接重试"
        ) from exc

    if resp.status_code == 401:
        return None
    try:
        body = _parse_json(resp, context=context)
    except OkkiApiError as exc:
        raise OkkiOutcomeUncertainError(
            f"OKKI {context}响应无法解析：订单可能已被受理，请先到 OKKI 后台确认，禁止直接重试"
        ) from exc
    if resp.status_code >= 500:
        detail = body.get("message") or resp.text[:500]
        raise OkkiOutcomeUncertainError(
            f"OKKI {context}服务异常（HTTP {resp.status_code}）：{detail}；"
            "订单可能已被受理，请先确认，禁止直接重试"
        )
    if body.get("error") == "access_denied":
        return None
    # 推单成功码保持严格（None/200）：push 是关键路径，未实测过 code=0 形态，不放宽
    if resp.status_code != 200 or (body.get("code") not in (None, 200)):
        detail = body.get("message") or body.get("error_description") or resp.text[:500]
        logger.warning("OKKI POST %s error %s: %s", path, resp.status_code, detail)
        print(f"[okki_client] POST {path} error {resp.status_code}: {detail}", flush=True)
        raise OkkiApiError(f"OKKI {context}失败：{detail}")
    return body.get("data") if isinstance(body.get("data"), dict) else body


def _get_json(path: str, token: str, *, context: str, params: dict | None = None) -> dict | None:
    """GET with Bearer auth. Returns payload data; None means auth failure
    (caller may retry with a fresh token); other failures raise.
    """
    try:
        # params 仅在显式传入时下发：既有测试桩/调用方按 (url, headers, timeout) 签名 mock
        extra = {"params": params} if params is not None else {}
        resp = httpx.get(
            f"{_base_url()}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
            **extra,
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
    if resp.status_code != 200 or (body.get("code") not in (None, 0, 200)):
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
