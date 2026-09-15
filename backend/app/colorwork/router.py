"""colorwork 集成路由：方舟页面权限 → 工作台 SSO；okki 实时库存状态回源。"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.colorwork.constants import VIEW_LABELS, VIEW_PERMISSIONS
from app.colorwork.service import (
    allowed_views_for,
    build_sso_url,
    compute_template_statuses,
    issue_sso_token,
    gateway_origin,
    gateway_sso_link,
    RELAY_HEADER,
    sync_secret,
)
from app.core.database import get_db

router = APIRouter()


@router.get("/sso")
def sso_entry(
    request: Request,
    response: Response,
    view: str = Query(..., description="工作台视图：library / inventory / master"),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按页面权限签发工作台 SSO 链接（前端 iframe 包装页调用）。

    用户持有目标页面对应的权限码才能拿到链接；令牌中带上用户全部可见视图，
    工作台据此刻内过滤导航。显示名取用户表 real_name（JWT payload 不含该字段）。
    """
    if view not in VIEW_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知的工作台视图: {view}",
        )
    views = allowed_views_for(user)
    if view not in views:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"权限不足，需要: {VIEW_PERMISSIONS[view]}",
        )
    response.headers["Cache-Control"] = "no-store"
    origin = gateway_origin(request.headers.get(RELAY_HEADER))
    if origin:
        return gateway_sso_link(view, request.headers.get("authorization", ""), origin)
    from app.auth.models import ArkUser

    db_user = db.get(ArkUser, int(user["sub"])) if str(user.get("sub", "")).isdigit() else None
    display_name = (db_user.real_name if db_user and db_user.real_name else None) or user.get("username") or "方舟用户"
    token = issue_sso_token(user, views, display_name)
    return {
        "url": build_sso_url(view, token),
        "view": view,
        "view_label": VIEW_LABELS[view],
        "views": views,
        "expires_in": 120,
    }


@router.get("/inventory-status")
def inventory_status(
    template_id: str = Query(..., description="工作台模板 id"),
    x_colorwork_sync_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """工作台服务端回源接口：按模板返回 ``{颜色}|{尺寸}`` → 状态 的实时映射。

    仅供工作台 worker 服务端调用（共享密钥头校验），不暴露给浏览器直访；
    只出有货状态，不出具体库存数量。
    """
    if not x_colorwork_sync_key or not hmac.compare_digest(
        x_colorwork_sync_key, sync_secret()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="同步密钥无效",
        )
    return compute_template_statuses(db, template_id)
