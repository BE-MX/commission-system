"""生产报工领域模块 — FastAPI router"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.dependencies import require_permission, require_any_permission
from app.production import (
    process_service, route_service, binding_service, report_service,
    dashboard_service,
)
from app.production.schemas import *

router = APIRouter()


# ════════════════════════════════════════════════════════════
# 生产看板
# ════════════════════════════════════════════════════════════

@router.get("/dashboard", summary="生产看板数据")
def get_dashboard(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    return dashboard_service.get_dashboard_data(db)


# ════════════════════════════════════════════════════════════
# 工序管理
# ════════════════════════════════════════════════════════════

@router.get("/processes", summary="工序列表")
def list_processes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    name: str | None = Query(None),
    status: int | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    items, total = process_service.list_processes(db, page=page, page_size=page_size, name=name, status=status)
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [
            {"id": i.id, "name": i.name, "description": i.description,
             "sort_order": i.sort_order, "status": i.status,
             "created_at": i.created_at, "updated_at": i.updated_at}
            for i in items
        ],
    }


@router.post("/processes", summary="创建工序", status_code=201)
def create_process(
    body: ProcessCreate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:admin")),
):
    try:
        obj = process_service.create_process(db, name=body.name, description=body.description, sort_order=body.sort_order)
        db.commit()
        return {"id": obj.id, "name": obj.name, "description": obj.description,
                "sort_order": obj.sort_order, "status": obj.status,
                "created_at": obj.created_at, "updated_at": obj.updated_at}
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.put("/processes/{process_id}", summary="编辑工序")
def update_process(
    process_id: int,
    body: ProcessUpdate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:admin")),
):
    try:
        obj = process_service.update_process(db, process_id, **body.model_dump(exclude_unset=True))
        db.commit()
        return {"id": obj.id, "name": obj.name, "description": obj.description,
                "sort_order": obj.sort_order, "status": obj.status,
                "created_at": obj.created_at, "updated_at": obj.updated_at}
    except LookupError:
        raise HTTPException(404, "工序不存在")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.delete("/processes/{process_id}", summary="删除工序")
def delete_process(
    process_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:admin")),
):
    try:
        process_service.delete_process(db, process_id)
        db.commit()
        return {"message": "工序已删除"}
    except LookupError:
        raise HTTPException(404, "工序不存在")
    except ValueError as e:
        raise HTTPException(409, str(e))


# ════════════════════════════════════════════════════════════
# 工序路线管理
# ════════════════════════════════════════════════════════════

@router.get("/process-routes", summary="路线列表")
def list_routes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    name: str | None = Query(None),
    status: int | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    items, total = route_service.list_routes(db, page=page, page_size=page_size, name=name, status=status)
    return {"total": total, "items": items}


@router.post("/process-routes", summary="创建路线", status_code=201)
def create_route(
    body: ProcessRouteCreate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:admin")),
):
    try:
        obj = route_service.create_route(db, name=body.name, description=body.description)
        db.commit()
        return {"id": obj.id, "name": obj.name, "description": obj.description,
                "status": obj.status, "step_count": 0, "product_count": 0,
                "created_at": obj.created_at, "updated_at": obj.updated_at}
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.put("/process-routes/{route_id}", summary="编辑路线")
def update_route(
    route_id: int,
    body: ProcessRouteUpdate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:admin")),
):
    try:
        obj = route_service.update_route(db, route_id, **body.model_dump(exclude_unset=True))
        db.commit()
        return {"id": obj.id, "name": obj.name, "description": obj.description,
                "status": obj.status, "created_at": obj.created_at, "updated_at": obj.updated_at}
    except LookupError:
        raise HTTPException(404, "路线不存在")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/process-routes/{route_id}/steps", summary="保存路线步骤（全量覆盖）")
def save_route_steps(
    route_id: int,
    body: RouteStepsSaveRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:admin")),
):
    try:
        steps = [{"process_id": s.process_id} for s in body.steps]
        result = route_service.save_route_steps(db, route_id, steps)
        db.commit()
        return {"route_id": route_id, "steps": result}
    except LookupError:
        raise HTTPException(404, "路线不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/process-routes/{route_id}/steps", summary="获取路线步骤")
def get_route_steps(
    route_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    steps = route_service.get_route_steps(db, route_id)
    return {"route_id": route_id, "steps": steps}


# ════════════════════════════════════════════════════════════
# 产品管理 + 路线绑定
# ════════════════════════════════════════════════════════════

@router.get("/products", summary="产品列表")
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    model: str | None = Query(None),
    group_name: str | None = Query(None),
    route_bound: str = Query("all"),
    show_disabled: bool = Query(False),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    items, total = binding_service.list_products(
        db, page=page, page_size=page_size, keyword=keyword,
        model=model, group_name=group_name, route_bound=route_bound,
        show_disabled=show_disabled,
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/products/filter-options", summary="产品筛选项")
def get_product_filter_options(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    return binding_service.get_product_filter_options(db)


@router.get("/products/{product_id}/process-route", summary="获取产品路线绑定")
def get_product_route(
    product_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    result = binding_service.get_product_route(db, product_id)
    if not result:
        raise HTTPException(404, "该产品未绑定工序路线")
    return result


@router.post("/products/{product_id}/process-route", summary="绑定/更换/解绑路线")
def bind_product_route(
    product_id: int,
    body: ProductRouteBindRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:write")),
):
    try:
        result = binding_service.bind_product_route(db, product_id, body.route_id)
        db.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/products/batch-bind-route", summary="批量绑定路线")
def batch_bind_route(
    body: BatchBindRouteRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:write")),
):
    try:
        result = binding_service.batch_bind_route(db, body.product_ids, body.route_id)
        db.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


# ════════════════════════════════════════════════════════════
# 用户工序绑定 + 微信ID
# ════════════════════════════════════════════════════════════

@router.get("/users/{user_id}/process-bindings", summary="查询用户工序绑定")
def get_user_bindings(
    user_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("user:read")),
):
    bindings = binding_service.get_user_bindings(db, user_id)
    return {"user_id": user_id, "bindings": bindings}


@router.put("/users/{user_id}/process-bindings", summary="更新用户工序绑定")
def update_user_bindings(
    user_id: int,
    body: UserProcessBindingUpdate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("user:write")),
):
    try:
        binding_service.update_user_bindings(db, user_id, body.process_ids)
        db.commit()
        return {"user_id": user_id, "process_ids": body.process_ids, "message": f"已更新 {len(body.process_ids)} 个工序绑定"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/users/{user_id}/wx-id", summary="更新用户微信ID")
def update_user_wx_id(
    user_id: int,
    body: UserWxIdUpdate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("user:write")),
):
    try:
        result = binding_service.update_user_wx_id(db, user_id, body.wx_id)
        db.commit()
        return {"user_id": user_id, "wx_id": result, "message": "微信ID已更新"}
    except ValueError as e:
        raise HTTPException(409, str(e))
    except LookupError:
        raise HTTPException(404, "用户不存在")


# ════════════════════════════════════════════════════════════
# 报工接口（无鉴权，供 Accio Work 本机调用）
# ════════════════════════════════════════════════════════════

@router.post("/report", summary="工人扫码报工（核心）")
def production_report(
    body: ReportRequest,
    db: Session = Depends(get_db),
):
    result = report_service.handle_production_report(db, body.qr_data, body.wx_id)
    db.commit()
    return result


# ════════════════════════════════════════════════════════════
# 进度初始化 / 查询
# ════════════════════════════════════════════════════════════

@router.post("/order-products/{order_product_id}/init-progress", summary="初始化工序进度")
def init_progress(
    order_product_id: int,
    body: InitProgressRequest | None = None,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("production:admin", "production:write")),
):
    force = body.force if body else False
    try:
        result = report_service.init_order_product_progress(db, order_product_id, force=force)
        db.commit()
        return result
    except LookupError:
        raise HTTPException(404, "订单产品不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/order-products/{order_product_id}/progress", summary="获取工序进度")
def get_progress(
    order_product_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    try:
        return report_service.get_order_product_progress(db, order_product_id)
    except LookupError:
        raise HTTPException(404, "该订单产品无进度记录")


# ════════════════════════════════════════════════════════════
# 二维码 / 打印卡
# ════════════════════════════════════════════════════════════

@router.get("/order-products/{order_product_id}/qrcode", summary="获取二维码")
def get_qrcode(
    order_product_id: int,
    size: int = Query(200, ge=100, le=500),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    try:
        return report_service.get_qrcode(db, order_product_id, size)
    except Exception:
        raise HTTPException(500, "二维码生成失败")


@router.get("/order-products/{order_product_id}/print-card", summary="获取打印卡数据")
def get_print_card(
    order_product_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    try:
        return report_service.get_print_card_data(db, order_product_id)
    except LookupError:
        raise HTTPException(404, "订单产品不存在")


# ════════════════════════════════════════════════════════════
# 公共数据（选择器用）
# ════════════════════════════════════════════════════════════

@router.get("/active-processes", summary="获取所有启用工序（选择器用）")
def get_active_processes(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    procs = process_service.get_active_processes(db)
    return [
        {"id": p.id, "name": p.name, "sort_order": p.sort_order}
        for p in procs
    ]


@router.get("/active-routes", summary="获取所有启用路线（选择器用）")
def get_active_routes(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("production:read")),
):
    routes = route_service.get_active_routes(db)
    return [
        {"id": r.id, "name": r.name, "description": r.description}
        for r in routes
    ]
