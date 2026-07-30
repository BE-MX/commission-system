"""采购节大屏公开路由（/api/public/festival）。

无 JWT 鉴权（宪法 3 白名单场景，已登记 scripts/check_conventions.py AUTH_EXEMPT_FILES）：
消费方是办公室 24 小时局域网大屏（192.168.101.193:8001/festival/），无登录态、断电重启后
需零人工恢复（key 固化在大屏书签 URL 里）。

门禁走必填 `key` 参数（Settings.FESTIVAL_SCREEN_KEYS，逗号分隔可多屏发放/单独吊销）：
**未配置任何 key 时端点整体关闭（fail-closed，与 stock/public_router 先例一致）**——
生产 nginx 将 /api 全量反代公网、北京云实例公网 IP 直挂，默认放开会把
业务员实名 + 新签金额 + 公司 GMV 匿名暴露。只读，只出榜单聚合数，无客户明细。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.festival import service

router = APIRouter()


def _require_key(key: str | None) -> None:
    raw = get_settings().FESTIVAL_SCREEN_KEYS or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise HTTPException(403, "大屏取数未配置访问 key（FESTIVAL_SCREEN_KEYS），端点关闭")
    if key not in keys:
        raise HTTPException(403, "Invalid or missing access key")


def _valid_date(value: str | None, field: str) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{field} 需为合法的 YYYY-MM-DD 日期")


@router.get("/new-sign", summary="个人新签积分榜（大屏取数，免登录白名单）")
def new_sign_board(
    key: str | None = Query(None, max_length=128),
    date_from: str | None = Query(None, description="预览窗口起（默认活动窗口 2026-08-01）"),
    date_to: str | None = Query(None, description="预览窗口止（默认 2026-08-31）"),
    db: Session = Depends(get_db),
):
    _require_key(key)
    _valid_date(date_from, "date_from")
    _valid_date(date_to, "date_to")
    return ok(service.get_screen_payload(db, date_from, date_to))
