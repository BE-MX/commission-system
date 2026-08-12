"""采购节大屏登录态路由（/api/festival）。

导航菜单「采购节看板」的换 key 通道：入口页 /festival/index.html 用主站
localStorage 的 JWT 调 /screen-key 换大屏访问 key，再跳 zhaiyao.html?key=。
key 本体只存 Settings.FESTIVAL_SCREEN_KEYS（.env），不进前端代码；
展厅电视等免登录场景仍走「书签 URL 固化 key」路径，与本端点无关。
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.festival import order_service

router = APIRouter()

FESTIVAL_PERMISSION = "festival:read"
FESTIVAL_ORDER_PERMISSION = "festival_order:read"


@router.get("/screen-key")
def get_screen_key(_user=Depends(require_permission(FESTIVAL_PERMISSION))):
    """用登录态换大屏访问 key。

    固定发第一个 key：轮换菜单用户 key 时在 .env 前置新 key（勿直接删第一个——
    电视书签可能固化了它）；get_settings 有 lru_cache，改 .env 后需重启后端生效。
    """
    raw = get_settings().FESTIVAL_SCREEN_KEYS or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise HTTPException(503, "大屏取数未配置访问 key（FESTIVAL_SCREEN_KEYS），请联系管理员")
    return ok({"key": keys[0]})


@router.get("/orders/summary")
def festival_order_summary(
    user_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission(FESTIVAL_ORDER_PERMISSION)),
):
    scope = order_service.resolve_scope(db, current_user, user_id)
    return ok(order_service.get_summary(db, scope))


@router.get("/orders")
def festival_orders(
    type: Literal["new_sign", "first_return", "repurchase"] = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    user_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission(FESTIVAL_ORDER_PERMISSION)),
):
    scope = order_service.resolve_scope(db, current_user, user_id)
    return ok(order_service.list_orders(db, type, scope, page, page_size, keyword))
