"""Stream the internal workbench through Ark's existing /api reverse proxy."""

import logging
import anyio
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.colorwork.service import WORKBENCH_PATH
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


# HTML/assets use a scoped HttpOnly SSO session, not Ark's localStorage Bearer token.
# Worker API handlers enforce requireView; SSO issuance remains protected by Ark RBAC.
@router.api_route("/workbench", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/workbench/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def workbench_proxy(request: Request, path: str = ""):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD"} and origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "不允许跨站修改工作台数据")
    # Fixed origin + original encoded path prevents traversal from becoming an open proxy.
    raw_path = request.scope.get("raw_path", request.url.path.encode()).decode("ascii")
    if not (raw_path == WORKBENCH_PATH or raw_path.startswith(WORKBENCH_PATH + "/")):
        raise HTTPException(400, "无效的工作台路径")
    upstream_url = internal_origin() + raw_path
    if request.url.query:
        upstream_url += "?" + request.url.query
    # Do not forward Ark bearer credentials or unrelated application cookies.
    excluded = _HOP_HEADERS | {"host", "authorization", "cookie", "forwarded", "referer"}
    excluded |= {name.strip().lower() for name in request.headers.get("connection", "").split(",")}
    headers = {key: value for key, value in request.headers.items()
               if key not in excluded and not key.startswith("x-forwarded-")}
    cookie = request.cookies.get("inventory_workbench_session")
    if cookie:
        headers["cookie"] = "inventory_workbench_session=" + cookie
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-host"] = request.url.netloc
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
    response.raw_headers = [(key, value) for key, value in upstream.headers.raw
                            if key.decode().lower() not in blocked]
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
