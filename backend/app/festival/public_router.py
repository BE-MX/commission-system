"""采购节大屏公开路由（/api/public/festival）。

无 JWT 鉴权（宪法 3 白名单场景，已登记 scripts/check_conventions.py AUTH_EXEMPT_FILES）：
消费方是办公室 24 小时局域网大屏（192.168.101.193:8001/festival/），无登录态、断电重启后
需零人工恢复（key 固化在大屏书签 URL 里）。

门禁走必填 `key` 参数（Settings.FESTIVAL_SCREEN_KEYS，逗号分隔可多屏发放/单独吊销）：
**未配置任何 key 时端点整体关闭（fail-closed，与 stock/public_router 先例一致）**——
生产 nginx 将 /api 全量反代公网、北京云实例公网 IP 直挂，默认放开会把
业务员实名 + 新签金额 + 公司 GMV 匿名暴露。只读，只出榜单聚合数，无客户明细。
"""

import time
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


def _norm_date(value: str | None, field: str) -> str | None:
    """校验并归一化为 YYYY-MM-DD（fromisoformat 接受 20260801 等变体，回填标准形再进 SQL）。"""
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(422, f"{field} 需为合法的 YYYY-MM-DD 日期")


# 进程内 30s 缓存：两屏 60s 轮询 × 多客户端时，把 custom_fields LIKE 全表扫的频率封顶。
# 单进程部署（NSSM 单 worker）无一致性问题；as_of 随缓存冻结，语义即“数据截至”。
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL = 55.0  # 与 30s/60s 前端轮询错拍，避免每次轮询都恰好 miss 全量重算


def _cached(kind: str, date_from: str | None, date_to: str | None, fn) -> dict:
    key = (kind, date_from, date_to)
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    if len(_CACHE) > 64:  # 预览窗口任意组合的增长兜底
        _CACHE.clear()
    data = fn()
    _CACHE[key] = (now, data)
    return data


@router.get("/new-sign", summary="个人新签积分榜（大屏取数，免登录白名单）")
def new_sign_board(
    key: str | None = Query(None, max_length=128),
    date_from: str | None = Query(None, description="预览窗口起（默认活动窗口 2026-08-01）"),
    date_to: str | None = Query(None, description="预览窗口止（默认 2026-08-31）"),
    db: Session = Depends(get_db),
):
    _require_key(key)
    date_from = _norm_date(date_from, "date_from")
    date_to = _norm_date(date_to, "date_to")
    return ok(_cached("new-sign", date_from, date_to,
                      lambda: service.get_screen_payload(db, date_from, date_to)))


@router.get("/camps", summary="阵营新签 PK 榜（大屏取数，免登录白名单）")
def camps_board(
    key: str | None = Query(None, max_length=128),
    date_from: str | None = Query(None, description="预览窗口起（默认活动窗口 2026-08-01）"),
    date_to: str | None = Query(None, description="预览窗口止（默认 2026-08-31）"),
    db: Session = Depends(get_db),
):
    _require_key(key)
    date_from = _norm_date(date_from, "date_from")
    date_to = _norm_date(date_to, "date_to")
    return ok(_cached("camps", date_from, date_to,
                      lambda: service.get_camps_payload(db, date_from, date_to)))


@router.get("/headline", summary="摘要头条屏（排名汇总 + 事件滚动流，免登录白名单）")
def headline_board(
    key: str | None = Query(None, max_length=128),
    date_from: str | None = Query(None, description="预览窗口起（预览时事件不落库）"),
    date_to: str | None = Query(None, description="预览窗口止"),
    db: Session = Depends(get_db),
):
    _require_key(key)
    date_from = _norm_date(date_from, "date_from")
    date_to = _norm_date(date_to, "date_to")
    return ok(_cached("headline", date_from, date_to,
                      lambda: service.get_headline_payload(db, date_from, date_to)))


_AI_TIP_TTL = 600.0  # AI 提示 10 分钟重算一次


@router.get("/ai-tip", summary="AI 赛事助手提示（免登录白名单，10 分钟缓存）")
def ai_tip(
    key: str | None = Query(None, max_length=128),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
):
    _require_key(key)
    date_from = _norm_date(date_from, "date_from")
    date_to = _norm_date(date_to, "date_to")
    cache_key = ("ai-tip", date_from, date_to)
    now = time.monotonic()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _AI_TIP_TTL:
        return ok(hit[1])
    headline = _cached("headline", date_from, date_to,
                       lambda: service.get_headline_payload(db, date_from, date_to))
    data = service.build_ai_tip(db, headline)
    _CACHE[cache_key] = (now, data)
    return ok(data)


@router.get("/repurchase", summary="首返·复购双榜（大屏取数，免登录白名单）")
def repurchase_board(
    key: str | None = Query(None, max_length=128),
    date_from: str | None = Query(None, description="预览窗口起（默认活动窗口 2026-08-01）"),
    date_to: str | None = Query(None, description="预览窗口止（默认 2026-09-30 复购窗）"),
    db: Session = Depends(get_db),
):
    _require_key(key)
    date_from = _norm_date(date_from, "date_from")
    date_to = _norm_date(date_to, "date_to")
    return ok(_cached("repurchase", date_from, date_to,
                      lambda: service.get_repurchase_payload(db, date_from, date_to)))


@router.get("/teams", summary="团队人均积分榜（大屏取数，免登录白名单）")
def teams_board(
    key: str | None = Query(None, max_length=128),
    date_from: str | None = Query(None, description="预览窗口起（默认活动窗口 2026-08-01）"),
    date_to: str | None = Query(None, description="预览窗口止（默认 2026-09-30 复购窗）"),
    db: Session = Depends(get_db),
):
    _require_key(key)
    date_from = _norm_date(date_from, "date_from")
    date_to = _norm_date(date_to, "date_to")
    return ok(_cached("teams", date_from, date_to,
                      lambda: service.get_teams_payload(db, date_from, date_to)))
