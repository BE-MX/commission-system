"""备货管理 — API 路由

权限码:
- stock:read      — 查看库存/日报
- stock:write     — 修改安全库存配置 / 触发 AI 建议
- stock:admin     — 管理(预留, 当前与 write 等价)
- production:read — 查看生产订单
- production:write— 创建/编辑生产订单 / 入库录入
- production:admin— 删除生产订单 / 管理全部订单
"""

from __future__ import annotations

import logging
from datetime import date
from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import require_permission
from app.stock import service
from app.stock.schemas import (
    AutoGenerateRequest,
    CartAddRequest,
    CartUpdateRequest,
    InTransitQueryRequest,
    OrderCreateRequest,
    OrderItemReceivedRequest,
    OrderItemStatusRequest,
    OrderItemUpdateRequest,
    OrderUpdateRequest,
    PrintJobCreateRequest,
    SafetyStockSaveRequest,
    TftPredictRequest,
)

logger = logging.getLogger("stock")
router = APIRouter()


def _ok(data, message: str = "ok", code: int = 200):
    return {"code": code, "message": message, "data": data}


def _get_user_id(user: dict) -> int:
    uid = int(user.get("sub") or user.get("user_id") or 0)
    if not uid:
        raise HTTPException(status_code=401, detail="无法识别当前用户")
    return uid


# ── GET /overview ──────────────────────────────────────
@router.get("/overview")
def get_overview(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="shortage,warning,sufficient,unset 逗号分隔"),
    sort: str = Query("sales_30d", pattern="^(sales_30d|sales_90d|enable_count|color)$"),
    order: str = Query("desc", pattern="^(desc|asc)$"),
    keyword: Optional[str] = Query(None, max_length=200),
    model: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    product_type: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    size: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    color: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    weight: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
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
    model: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    product_type: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    size: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    color: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    weight: Optional[str] = Query(None, max_length=500, description="逗号分隔，支持多选"),
    sort: str = Query("product_id", pattern="^(product_id|sales_30d|enable_count|safety_stock|color)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    has_in_transit: Optional[bool] = Query(None, description="仅显示有生产在途的产品"),
    has_safety_stock: Optional[bool] = Query(None, description="仅显示已设置安全库存的产品"),
    stock_status: Optional[str] = Query(None, pattern="^(stocking|urgent)$", description="备货状态筛选: stocking=备货中, urgent=加急中"),
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
        sort_by=sort,
        order=order,
        has_in_transit=has_in_transit,
        has_safety_stock=has_safety_stock,
        stock_status=stock_status,
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


# ── GET /filter-options ────────────────────────────────
@router.get("/filter-options")
def get_filter_options(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """全部产品的筛选维度可选值(型号/类型/尺寸/颜色/克重)"""
    opts = service.get_filter_options(db=db)
    return _ok(opts)


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


# ── POST /daily-report/push ─────────────────────────────
@router.post("/daily-report/push")
def push_daily_report_endpoint(
    report_date_value: Optional[date] = Query(None, alias="report_date"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:admin")),
):
    """手动触发钉钉推送(日报不存在时先自动生成)"""
    from app.stock.scheduler import generate_stock_daily_report_sync
    from app.stock.daily_report_service import push_daily_report

    target_date = report_date_value or date.today()

    # 检查日报是否存在
    rec = service.get_daily_report(db=db, report_date_value=target_date)
    if not rec:
        # 不存在则生成(不推送)
        generate_stock_daily_report_sync(db=db, target_date=target_date, push_dingtalk=False)
        rec = service.get_daily_report(db=db, report_date_value=target_date)

    if not rec:
        raise HTTPException(status_code=500, detail="日报生成失败")

    # 推送钉钉
    shortage_skus = rec.get("shortage_skus", [])
    warning_skus = rec.get("warning_skus", [])
    summary = {
        "shortage_count": rec.get("shortage_count", 0),
        "warning_count": rec.get("warning_count", 0),
        "sufficient_count": rec.get("sufficient_count", 0),
    }

    push_daily_report(db, target_date, shortage_skus, warning_skus, summary)
    service.mark_daily_report_pushed(db, target_date)

    return _ok(
        {"report_date": target_date.isoformat(), "dingtalk_sent": True},
        message="钉钉推送已发送",
    )


# ═══════════════════════════════════════════════════════════════
# 生产单购物车
# ═══════════════════════════════════════════════════════════════

@router.get("/production/cart")
def get_cart(
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """购物车列表"""
    user_id = _get_user_id(user)
    items = service.get_cart_list(db, user_id)
    count = service.get_cart_count(db, user_id)
    return _ok({"items": items, "count": count})


@router.post("/production/cart")
def add_to_cart(
    req: CartAddRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """加入购物车(已存在则更新)"""
    user_id = _get_user_id(user)
    result = service.add_or_update_cart(
        db,
        user_id=user_id,
        product_id=req.product_id,
        product_name=req.product_name,
        model=req.model,
        spec_info=req.spec_info,
        order_qty=req.order_qty,
        remark=req.remark,
    )
    action_label = "更新" if result["action"] == "updated" else "添加"
    return _ok(result, message=f"已{action_label}到购物车")


@router.put("/production/cart/{cart_id}")
def update_cart(
    cart_id: int,
    req: CartUpdateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """更新购物车项"""
    user_id = _get_user_id(user)
    ok = service.update_cart_item(db, user_id, cart_id, req.order_qty, req.remark)
    if not ok:
        raise HTTPException(status_code=404, detail="购物车项不存在")
    return _ok(None, message="已更新")


@router.delete("/production/cart/{cart_id}")
def remove_from_cart(
    cart_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """删除购物车单项"""
    user_id = _get_user_id(user)
    ok = service.delete_cart_item(db, user_id, cart_id)
    if not ok:
        raise HTTPException(status_code=404, detail="购物车项不存在")
    return _ok(None, message="已删除")


@router.delete("/production/cart")
def clear_cart(
    cart_ids: list[int] = Query(..., description="要删除的购物车ID列表"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """批量删除购物车项"""
    user_id = _get_user_id(user)
    deleted = service.delete_cart_items(db, user_id, cart_ids)
    return _ok({"deleted_count": deleted}, message=f"已删除 {deleted} 项")


# ═══════════════════════════════════════════════════════════════
# 生产在途查询
# ═══════════════════════════════════════════════════════════════

@router.post("/production/in-transit")
def query_in_transit(
    req: InTransitQueryRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """批量查询生产在途数量"""
    result = service.get_in_transit_by_product_ids(db, req.product_ids)
    items = [{"product_id": pid, "in_transit_qty": qty} for pid, qty in result.items()]
    return _ok({"items": items})


@router.post("/production/stock-status")
def query_stock_status(
    req: InTransitQueryRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("stock:read")),
):
    """批量查询产品备货状态"""
    result = service.get_stock_status_by_product_ids(db, req.product_ids)
    items = [
        {"product_id": pid, "stock_status": v["stock_status"], "has_urgent": v["has_urgent"], "items": v["items"]}
        for pid, v in result.items()
    ]
    return _ok({"items": items})


# ═══════════════════════════════════════════════════════════════
# 生产订单管理
# ═══════════════════════════════════════════════════════════════

@router.post("/production/orders")
def create_production_order(
    req: OrderCreateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """从购物车生成生产订单"""
    user_id = _get_user_id(user)
    cart_items = service.get_cart_items_by_ids(db, user_id, req.cart_ids)
    if not cart_items:
        raise HTTPException(status_code=400, detail="未找到有效的购物车项")

    # 检查是否有失效产品(简单检查:产品名不能为空)
    invalid = [c for c in cart_items if not c.get("product_name")]
    if invalid:
        raise HTTPException(status_code=400, detail="选中的产品存在失效项,请移除后重试")

    try:
        result = service.create_order(
            db,
            cart_items=cart_items,
            batch_no=req.batch_no,
            remark=req.remark,
            is_urgent=req.is_urgent,
            expected_delivery_date=req.expected_delivery_date,
            operator_id=user_id,
            operator_name=user.get("username", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 从购物车移除已选中的
    service.delete_cart_items(db, user_id, req.cart_ids)

    return _ok(result, message="生产订单创建成功", code=201)


@router.get("/production/orders")
def list_production_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[int] = Query(None, ge=0, le=2),
    keyword: Optional[str] = Query(None, max_length=200),
    sort_field: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("production:read")),
):
    """生产订单列表(按订单维度)"""
    result = service.get_order_list(db, page=page, page_size=page_size, status=status, keyword=keyword, sort_field=sort_field, sort_order=sort_order)
    return _ok({
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": result["items"],
    })


@router.get("/production/orders/{order_id}")
def get_production_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("production:read")),
):
    """生产订单详情"""
    detail = service.get_order_detail(db, order_id)
    if not detail:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    return _ok(detail)


@router.put("/production/orders/{order_id}")
def update_production_order(
    order_id: int,
    req: OrderUpdateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """编辑生产订单(含状态变更,级联同步明细)"""
    user_id = _get_user_id(user)
    try:
        ok = service.update_order(
            db, order_id,
            batch_no=req.batch_no,
            remark=req.remark,
            status=req.status,
            operator_id=user_id,
            operator_name=user.get("username", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    return _ok(None, message="已更新")


@router.delete("/production/orders/{order_id}")
def delete_production_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:admin")),
):
    """删除生产订单(软删,已入库的不允许)"""
    user_id = _get_user_id(user)
    try:
        ok = service.delete_order(db, order_id, operator_id=user_id, operator_name=user.get("username", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail="生产订单不存在")
    return _ok(None, message="已删除")


# ── 明细 ──────────────────────────────────────────────────────

@router.get("/production/order-items")
def list_production_order_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[int] = Query(None, ge=0, le=2),
    keyword: Optional[str] = Query(None, max_length=200),
    sort_field: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("production:read")),
):
    """生产订单明细列表(按明细维度,标签页二用)"""
    result = service.get_order_item_list(db, page=page, page_size=page_size, status=status, keyword=keyword, sort_field=sort_field, sort_order=sort_order)
    return _ok({
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": result["items"],
    })


@router.put("/production/order-items/{item_id}")
def update_production_order_item(
    item_id: int,
    req: OrderItemUpdateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """编辑生产订单明细"""
    user_id = _get_user_id(user)
    try:
        ok = service.update_order_item(
            db, item_id,
            order_qty=req.order_qty,
            remark=req.remark,
            is_urgent=req.is_urgent,
            expected_delivery_date=req.expected_delivery_date,
            operator_id=user_id,
            operator_name=user.get("username", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail="明细不存在")
    return _ok(None, message="已更新")


@router.put("/production/order-items/{item_id}/status")
def update_production_item_status(
    item_id: int,
    req: OrderItemStatusRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """修改明细状态(双向同步订单状态)"""
    user_id = _get_user_id(user)
    ok = service.update_item_status(
        db, item_id, req.status,
        operator_id=user_id,
        operator_name=user.get("username", ""),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="明细不存在")
    return _ok(None, message="状态已更新")


@router.put("/production/order-items/{item_id}/received")
def update_production_item_received(
    item_id: int,
    req: OrderItemReceivedRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """录入已入库数量(入库完成自动改状态为已完成)"""
    user_id = _get_user_id(user)
    try:
        ok = service.update_item_received(
            db, item_id, req.received_qty,
            operator_id=user_id,
            operator_name=user.get("username", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail="明细不存在")
    return _ok(None, message="入库数量已更新")


@router.delete("/production/order-items/{item_id}")
def delete_production_order_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:admin")),
):
    """删除生产订单明细(已入库的不允许)"""
    user_id = _get_user_id(user)
    try:
        ok = service.delete_order_item(db, item_id, operator_id=user_id, operator_name=user.get("username", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not ok:
        raise HTTPException(status_code=404, detail="明细不存在")
    return _ok(None, message="已删除")


@router.post("/production/orders/{order_id}/reset-process", summary="重置订单工艺进度")
def reset_order_process(
    order_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """删除订单下所有明细的工序进度，按最新产品工艺路线重新生成。"""
    from app.production.models import OrderProductProcessProgress, ProcessRouteStep, ProductProcessRoute
    from app.stock.models import ProductionOrder, ProductionOrderItem

    order = db.query(ProductionOrder).filter(
        ProductionOrder.id == order_id, ProductionOrder.deleted_flag == 0
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="生产订单不存在")

    items = db.query(ProductionOrderItem).filter(
        ProductionOrderItem.order_id == order_id,
    ).all()

    item_ids = [item.id for item in items]
    if item_ids:
        db.query(OrderProductProcessProgress).filter(
            OrderProductProcessProgress.order_product_id.in_(item_ids)
        ).delete(synchronize_session=False)

    success_count = 0
    errors = []
    for item in items:
        binding = db.query(ProductProcessRoute).filter(ProductProcessRoute.product_id == item.product_id).first()
        if not binding:
            errors.append({"item_id": item.id, "product_name": item.product_name, "error": "未绑定工序路线"})
            continue

        steps = (
            db.query(ProcessRouteStep)
            .filter(ProcessRouteStep.route_id == binding.route_id)
            .order_by(ProcessRouteStep.step_order)
            .all()
        )
        if not steps:
            errors.append({"item_id": item.id, "product_name": item.product_name, "error": "工序路线无工序"})
            continue

        for step in steps:
            db.add(OrderProductProcessProgress(
                order_product_id=item.id,
                process_id=step.process_id,
                route_id=binding.route_id,
                step_order=step.step_order,
                status=0,
            ))
        success_count += 1

    db.commit()
    return _ok({
        "total": len(items),
        "success": success_count,
        "errors": errors,
    }, message=f"工艺重置完成，成功 {success_count}/{len(items)}")


# ── 二维码图片（供 jimureport 报表直接引用）──────────────────
@router.get("/production/qrcode-image")
def get_order_qrcode_image(
    order_no: str = Query(..., description="生产订单号"),
    size: int = Query(200, ge=100, le=500),
):
    """根据 order_no 生成二维码 PNG，供报表 img src 直接使用（无需鉴权）"""
    import qrcode
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(order_no)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


# ═══════════════════════════════════════════════════════════════
# 生产订单打印工作台
# ═══════════════════════════════════════════════════════════════

@router.get("/production/print-orders")
def list_print_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, max_length=200),
    status: Optional[int] = Query(None, ge=0, le=2),
    print_state: Optional[str] = Query(None, pattern=r"^(unprinted|today|week)$"),
    sort_field: str = Query("created_at"),
    sort_order: str = Query("desc", pattern=r"^(asc|desc)$"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("production:read")),
):
    """打印工作台-订单列表(含最后打印时间)"""
    from app.stock.print_workstation_service import get_print_order_list
    result = get_print_order_list(
        db, page=page, page_size=page_size, keyword=keyword,
        status=status, print_state=print_state,
        sort_field=sort_field, sort_order=sort_order,
    )
    return _ok(result)


@router.get("/production/orders/{order_id}/print-categories")
def get_print_categories(
    order_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("production:read")),
):
    """获取订单的分类卡片(打印工作台-展开)"""
    from app.stock.print_workstation_service import get_order_print_categories
    result = get_order_print_categories(db, order_id)
    return _ok(result)


@router.post("/production/orders/{order_id}/print-jobs")
def create_print_job(
    order_id: int,
    body: PrintJobCreateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("production:write")),
):
    """创建打印记录并返回打印URL"""
    from app.stock.print_workstation_service import create_print_job as _create_print_job
    try:
        result = _create_print_job(
            db, order_id=order_id, scope=body.scope,
            category_index=body.category_index,
            item_ids=body.item_ids,
            user_id=user["sub"], user_name=user.get("real_name", ""),
        )
        return _ok(result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
