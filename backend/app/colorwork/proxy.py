"""Stream the internal workbench through Ark's existing /api reverse proxy."""

import logging
from http.cookies import SimpleCookie
import anyio
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.colorwork.service import WORKBENCH_PATH, RELAY_HEADER, gateway_origin
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailer", "transfer-encoding", "upgrade"}


def internal_origin() -> str:
    origin = get_settings().COLORWORK_INTERNAL_ORIGIN.rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise HTTPException(503, "库存色块图工作台内部服务地址配置无效")
    return origin


def _allows_mutation_origin(request: Request, origin: str | None) -> bool:
    """Allow the loopback dev frontend to call the local API proxy.

    Production traffic remains same-origin.  The development frontend runs on
    port 3000 while the API runs on 8001, so rejecting every cross-origin
    mutation prevents local PSD/JPG uploads before they reach the workbench.
    """
    if not origin:
        return True
    if origin == str(request.base_url).rstrip("/"):
        return True
    if getattr(get_settings(), "APP_ENV", "production") == "production":
        return False
    parsed = urlsplit(origin)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.port in {3000, 5173, 5174}
    )


async def _close(response, client):
    with anyio.CancelScope(shield=True):
        if response is not None:
            await response.aclose()
        await client.aclose()


async def _stream(response, client):
    try:
        async for chunk in response.aiter_raw():
            yield chunk
    finally:
        await _close(response, client)


def _gateway_headers(headers, gateway, secure):
    """Keep the Beijing session on the browser's LAN origin, including plain HTTP."""
    result = []
    for key, value in headers:
        if key.lower() == b"set-cookie":
            cookies = SimpleCookie()
            cookies.load(value.decode("latin-1"))
            cookie = cookies.get("inventory_workbench_session")
            if cookie is None:
                continue
            cookie["domain"] = ""
            cookie["path"] = WORKBENCH_PATH
            cookie["secure"] = secure
            cookie["httponly"] = True
            cookie["samesite"] = "Lax"
            value = cookie.OutputString().encode("latin-1")
        elif key.lower() == b"location":
            target = urlsplit(value.decode("latin-1"))
            owner = urlsplit(gateway)
            if target.netloc:
                if target.scheme != owner.scheme or target.netloc != owner.netloc:
                    raise HTTPException(502, "库存色块图工作台返回了无效的跳转")
                value = (target.path + ("?" + target.query if target.query else "")).encode("latin-1")
        result.append((key, value))
    return result


# HTML/assets use a scoped HttpOnly SSO session, not Ark's localStorage Bearer token.
# Worker API handlers enforce requireView; SSO issuance remains protected by Ark RBAC.
@router.api_route("/workbench", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/workbench/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def workbench_proxy(request: Request, path: str = ""):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD"} and not _allows_mutation_origin(request, origin):
        raise HTTPException(403, "不允许跨站修改工作台数据")
    # Fixed origin + original encoded path prevents traversal from becoming an open proxy.
    raw_path = request.scope.get("raw_path", request.url.path.encode()).decode("ascii")
    if not (raw_path == WORKBENCH_PATH or raw_path.startswith(WORKBENCH_PATH + "/")):
        raise HTTPException(400, "无效的工作台路径")
    gateway = gateway_origin(request.headers.get(RELAY_HEADER))
    target_origin = gateway or internal_origin()
    upstream_url = target_origin + raw_path
    if request.url.query:
        upstream_url += "?" + request.url.query
    # Do not forward Ark bearer credentials or unrelated application cookies.
    excluded = _HOP_HEADERS | {"host", "authorization", "cookie", "forwarded", "referer", RELAY_HEADER}
    excluded |= {name.strip().lower() for name in request.headers.get("connection", "").split(",")}
    headers = {key: value for key, value in request.headers.items()
               if key not in excluded and not key.startswith("x-forwarded-")}
    cookie = request.cookies.get("inventory_workbench_session")
    if cookie:
        headers["cookie"] = "inventory_workbench_session=" + cookie
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-host"] = request.url.netloc
    if gateway:
        headers[RELAY_HEADER] = "1"
        # Browser origin was checked above. The owner must see its own HTTPS
        # origin even when the local development frontend is on port 3000.
        if origin:
            headers["origin"] = gateway
        headers["x-forwarded-proto"] = "https"
        headers["x-forwarded-host"] = urlsplit(gateway).netloc
    client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=3), follow_redirects=False, trust_env=False)
    try:
        upstream = await client.send(client.build_request(
            request.method, upstream_url, headers=headers,
            content=None if request.method in {"GET", "HEAD"} else request.stream(),
        ), stream=True)
    except httpx.HTTPError as error:
        await client.aclose()
        # URLs contain short-lived SSO tokens: log the error type only.
        logger.warning("Colorwork runtime unavailable: %s", type(error).__name__)
        print("Colorwork runtime unavailable: " + type(error).__name__, flush=True)
        raise HTTPException(503, "库存色块图工作台服务尚未启动，请联系管理员完成平台部署。") from None
    except BaseException:
        await _close(None, client)
        raise
    response = StreamingResponse(_stream(upstream, client), status_code=upstream.status_code)
    blocked = _HOP_HEADERS | {"content-security-policy", "x-frame-options"}
    blocked |= {name.strip().lower() for name in upstream.headers.get("connection", "").split(",")}
    raw_headers = [(key, value) for key, value in upstream.headers.raw
                   if key.decode().lower() not in blocked]
    try:
        response.raw_headers = _gateway_headers(raw_headers, gateway, request.url.scheme == "https") if gateway else raw_headers
    except BaseException:
        await _close(upstream, client)
        raise
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
