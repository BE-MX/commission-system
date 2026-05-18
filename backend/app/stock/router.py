"""备货管理 — API 路由

权限码:
- stock:read  — 查看库存/日报
- stock:write — 修改安全库存配置 / 触发 AI 建议
- stock:admin — 管理(预留, 当前与 write 等价)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import require_permission
from app.stock import service
from app.stock.schemas import (
    AutoGenerateRequest,
    SafetyStockSaveRequest,
    TftPredictRequest,
)

logger = logging.getLogger("stock")
router = APIRouter()


def _ok(data, message: str = "ok", code: int = 200):
    return {"code": code, "message": message, "data": data}


# ── GET /overview ──────────────────────────────────────
@router.get("/overview")
def get_overview(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="shortage,warning,sufficient,unset 逗号分隔"),
    sort: str = Query("sales_30d", pattern="^(sales_30d|sales_90d|enable_count)$"),
    order: str = Query("desc", pattern="^(desc|asc)$"),
    keyword: Optional[str] = Query(None, max_length=200),
    model: Optional[str] = Query(None, max_length=100),
    product_type: Optional[str] = Query(None, max_length=100),
    size: Optional[str] = Query(None, max_length=100),
    color: Optional[str] = Query(None, max_length=100),
    weight: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """销量备货一览"""
    status_filter = [s for s in (status or "").split(",") if s] or None
    result = service.query_stock_overview(
        db=db,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        sort_by=sort,
        order=order,
        keyword=keyword,
        model=model,
        product_type=product_type,
        size=size,
        color=color,
        weight=weight,
    )
    return _ok({
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "summary": result["summary"],
        "items": result["items"],
    })


# ── GET /safety ────────────────────────────────────────
@router.get("/safety")
def get_safety_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    keyword: Optional[str] = Query(None, max_length=200),
    model: Optional[str] = Query(None, max_length=100),
    product_type: Optional[str] = Query(None, max_length=100),
    size: Optional[str] = Query(None, max_length=100),
    color: Optional[str] = Query(None, max_length=100),
    weight: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """安全库存列表(用于设置页)"""
    result = service.query_safety_stock_list(
        db=db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        model=model,
        product_type=product_type,
        size=size,
        color=color,
        weight=weight,
    )
    return _ok({
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": result["items"],
    })


# ── POST /safety ───────────────────────────────────────
@router.post("/safety")
def save_safety(
    req: SafetyStockSaveRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("stock:write")),
):
    """批量保存安全库存"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    if not user_id:
        raise HTTPException(status_code=401, detail="无法识别当前用户")

    if not req.items:
        return _ok({"saved_count": 0, "failed_items": []})

    result = service.save_safety_stock(
        db=db,
        items=[i.model_dump() for i in req.items],
        lead_time_days=req.lead_time_days,
        safety_factor=req.safety_factor,
        source=service.SOURCE_MANUAL,
        updated_by=user_id,
    )

    saved_count = len(result["saved"])
    failed = result["failed"]
    if failed and saved_count:
        return _ok(
            {"saved_count": saved_count, "failed_items": failed},
            message="部分保存成功",
        )
    if failed and not saved_count:
        return _ok(
            {"saved_count": 0, "failed_items": failed},
            message="保存失败",
        )
    return _ok({"saved_count": saved_count, "failed_items": []}, message="保存成功")


# ── POST /safety/auto-generate ─────────────────────────
@router.post("/safety/auto-generate")
async def auto_generate(
    req: AutoGenerateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:write")),
):
    """AI 批量生成安全库存建议(不写库,前端确认后再调 POST /safety)"""
    result = await service.batch_generate_suggestions(
        db=db,
        product_ids=req.product_ids,
        lead_time_days=req.lead_time_days,
        safety_factor=req.safety_factor,
        history_days=req.history_days,
    )
    return _ok(result)


# ── POST /tft-predict ──────────────────────────────────
@router.post("/tft-predict")
async def tft_predict(
    req: TftPredictRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """TFT 预测单个 SKU(未部署时公式兜底)"""
    result = await service.get_safety_stock_suggestion(
        db=db,
        product_id=req.product_id,
        lead_time_days=30,
        safety_factor=1.5,
        history_days=req.history_days,
    )
    return _ok(result)


# ── GET /daily-report ──────────────────────────────────
@router.get("/daily-report")
def get_latest_daily_report(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """最新一条库存日报"""
    rec = service.get_daily_report(db=db)
    if not rec:
        raise HTTPException(status_code=404, detail="暂无库存日报")
    return _ok(rec)


# ── GET /daily-report/{date} ──────────────────────────
@router.get("/daily-report/{report_date}")
def get_daily_report_by_date(
    report_date: date,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """指定日期库存日报"""
    rec = service.get_daily_report(db=db, report_date_value=report_date)
    if not rec:
        raise HTTPException(status_code=404, detail=f"未找到 {report_date} 的库存日报")
    return _ok(rec)


# ── POST /daily-report/generate ────────────────────────
@router.post("/daily-report/generate")
def trigger_daily_report(
    report_date_value: Optional[date] = Query(None, alias="report_date"),
    push_dingtalk: bool = Query(False, description="是否推送钉钉"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:admin")),
):
    """手动触发日报生成(管理员调试用)"""
    from app.stock.scheduler import generate_stock_daily_report_sync

    target_date = report_date_value or date.today()
    rec = generate_stock_daily_report_sync(db=db, target_date=target_date, push_dingtalk=push_dingtalk)
    return _ok({
        "report_date": rec.report_date.isoformat(),
        "shortage_count": rec.shortage_count,
        "warning_count": rec.warning_count,
        "sufficient_count": rec.sufficient_count,
        "dingtalk_sent": bool(rec.dingtalk_sent),
    }, message="已生成")
