"""media.leshine.cloud 客户只读门户 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.customer_media import service
from app.customer_media.router import _asset
from app.customer_media.schemas import PortalLoginIn
from app.customer_media.storage import storage_for
from app.pm.auth import EntryRateLimiter, client_ip


router = APIRouter()
settings = get_settings()
login_email_limiter = EntryRateLimiter(5)
login_ip_limiter = EntryRateLimiter(20)
PORTAL_HEADERS = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class PortalSecurityHeadersMiddleware:
    """为客户门户全部 API（包含框架错误响应）附加禁止缓存头。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or not path.startswith("/api/customer-media/portal"):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                replaced = {name.lower().encode("latin-1") for name in PORTAL_HEADERS}
                headers = [
                    (name, value) for name, value in message.get("headers", [])
                    if name.lower() not in replaced
                ]
                headers.extend(
                    (name.lower().encode("latin-1"), value.encode("latin-1"))
                    for name, value in PORTAL_HEADERS.items()
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _error(exc: Exception):
    if isinstance(exc, service.CustomerMediaNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if isinstance(exc, service.CustomerMediaForbidden):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    raise exc


def _session_account(request: Request, db: Session):
    try:
        return service.portal_session(db, request.cookies.get(settings.CUSTOMER_MEDIA_COOKIE_NAME))
    except Exception as exc:
        _error(exc)


@router.post("/login")
def login(data: PortalLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = str(data.email).strip().lower()
    ip = client_ip(request)
    if login_email_limiter.exceeded(email) or login_ip_limiter.exceeded(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "尝试次数过多，请稍后再试")
    try:
        account, token, expires = service.authenticate_portal(
            db, email, data.password, ip, request.headers.get("user-agent", ""),
            settings.CUSTOMER_MEDIA_SESSION_DAYS,
        )
    except service.CustomerMediaForbidden as exc:
        login_email_limiter.hit_and_check(email)
        login_ip_limiter.hit_and_check(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误") from exc
    response.set_cookie(
        settings.CUSTOMER_MEDIA_COOKIE_NAME,
        token,
        max_age=settings.CUSTOMER_MEDIA_SESSION_DAYS * 86400,
        expires=settings.CUSTOMER_MEDIA_SESSION_DAYS * 86400,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/api/customer-media/portal",
    )
    return ok({"customer_id": account.customer_id, "customer_name": account.customer_name_snapshot, "email": account.login_email})


@router.post("/logout")
# require_permission exemption: 外部门户使用 HttpOnly 会话 cookie，由 portal_session 校验。
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    service.revoke_portal_session(db, request.cookies.get(settings.CUSTOMER_MEDIA_COOKIE_NAME))
    response.delete_cookie(settings.CUSTOMER_MEDIA_COOKIE_NAME, path="/api/customer-media/portal")
    return ok(None, "已退出")


@router.get("/me")
# require_permission exemption: 外部门户使用 HttpOnly 会话 cookie，由 _session_account 校验。
def me(request: Request, db: Session = Depends(get_db)):
    account = _session_account(request, db)
    return ok({"customer_id": account.customer_id, "customer_name": account.customer_name_snapshot, "email": account.login_email})


@router.get("/library")
# require_permission exemption: 外部门户使用 HttpOnly 会话 cookie，并按 customer_id 过滤。
def library(
    request: Request,
    tag_value_ids: str | None = Query(default=None, max_length=1000),
    db: Session = Depends(get_db),
):
    account = _session_account(request, db)
    rows = service.portal_library(db, account)
    matching = service.matching_asset_ids(db, rows, service.parse_tag_value_ids(tag_value_ids))
    asset_ids = [asset.id for row in rows for asset in row.assets if asset.deleted_at is None]
    tags_map = service.asset_tags_map(db, asset_ids)
    task_meta = service.portal_task_meta(db, rows)
    items = []
    for row in rows:
        assets = [
            _asset(asset, internal=False, tags=tags_map.get(asset.id, []))
            for asset in row.assets
            if asset.deleted_at is None and (matching is None or asset.id in matching)
        ]
        if matching is not None and not assets:
            continue
        items.append({
            "id": row.id,
            "task_id": row.task_id,
            "revision": row.revision,
            "title": task_meta.get(row.task_id, {}).get("task_name") or "拍摄交付",
            "shoot_type": task_meta.get(row.task_id, {}).get("shoot_type"),
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "assets": assets,
        })
    return ok(items)


@router.get("/tags")
# require_permission exemption: 外部门户使用 HttpOnly 会话 cookie，仅出该客户已发布素材实际用到的标签。
def tags(request: Request, db: Session = Depends(get_db)):
    account = _session_account(request, db)
    return ok(service.portal_used_tags(db, account))


@router.get("/assets/{asset_id}/content")
# require_permission exemption: 外部门户使用 HttpOnly 会话 cookie，portal_asset 再校验客户和发布状态。
def content(
    asset_id: int,
    request: Request,
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    account = _session_account(request, db)
    try:
        asset = service.portal_asset(db, account, asset_id)
    except Exception as exc:
        _error(exc)
    response = storage_for(asset.storage_provider).response(asset, download=download)
    if download:
        service.log_download(db, asset.id, account.id, client_ip(request))
    return response
