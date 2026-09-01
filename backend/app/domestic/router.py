"""内贸订单管理 — API 路由

权限：domestic:read（查看）/ domestic:write（下单、编辑、发货、报工）/
domestic:admin（工艺路线映射、产品改绑、删单、撤销他人报工）。
统一信封 ok()；用户 ID 一律 int(current_user["sub"])（cerebrum 2026-07-13）。
"""

import base64
import io
import logging
from datetime import date, datetime
from app.core.time import beijing_now
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.domestic import constants as C
from app.domestic import (
    attribute_service,
    balance_service,
    customer_service,
    export_service,
    file_service,
    order_service,
    pricing_service,
    product_service,
    progress_service,
    report_service,
    route_rule_service,
    unit_service,
)
from app.domestic.models import DomesticOrder, DomesticOrderItem
from app.domestic.schemas import (
    BasePriceUpdate,
    CraftRouteUpsert,
    CustomerCreate,
    CustomerRechargeCreate,
    CustomerUpdate,
    ItemShipRequest,
    OrderCreate,
    OrderItemAppend,
    OrderItemUpdate,
    OrderStatusUpdate,
    OrderUpdate,
    ProductRouteRebind,
    PricingQuoteRequest,
    ManualSkipSubmit,
    ReportRevoke,
    ReportSubmit,
    RouteRuleSaveRequest,
    RouteConfigurationSaveRequest,
)
from app.auth.models import ArkUser
from app.production.models import Process, ProcessRoute, ProcessRouteStep, UserProcessBinding

logger = logging.getLogger("commission")

router = APIRouter()

_READ = ("domestic:read", "domestic:write", "domestic:admin")
_CUSTOMER_READ = (*_READ, "domestic:recharge")


def _uid(current_user: dict) -> int:
    return int(current_user["sub"])


def _has_admin(current_user: dict) -> bool:
    if "super_admin" in (current_user.get("roles") or []):
        return True
    return "domestic:admin" in (current_user.get("permissions") or [])


# ── 下拉值域 ──────────────────────────────────────────


@router.get("/options", summary="下单表单的全部下拉值域")
def get_options(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    """一次给全：产品类型、订单类型 + 各属性字典。前端按 product_type 条件渲染。"""
    return ok(attribute_service.get_order_options(db))


@router.get("/process-routes", summary="可选工艺路线（配映射/改绑用）")
def list_process_routes(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    routes = db.query(ProcessRoute).filter(ProcessRoute.status == 1).order_by(ProcessRoute.id.asc()).all()
    steps = db.query(ProcessRouteStep.route_id, ProcessRouteStep.process_id, ProcessRouteStep.step_order).all()
    names = dict(db.query(Process.id, Process.name).all())
    by_route: dict[int, list] = {}
    for route_id, process_id, step_order in steps:
        by_route.setdefault(route_id, []).append((step_order, names.get(process_id, "")))
    return ok([{
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "step_count": len(by_route.get(r.id, [])),
        "steps": [n for _, n in sorted(by_route.get(r.id, []))],
    } for r in routes])


@router.get("/process-routes/{route_id}/rules", summary="查询内贸条件路线规则")
def get_process_route_rules(
    route_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    try:
        return ok(route_rule_service.list_rules(db, route_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/process-routes/{route_id}/rules", summary="全量保存内贸条件路线规则")
def put_process_route_rules(
    route_id: int,
    payload: RouteRuleSaveRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        data = route_rule_service.save_rules(
            db,
            route_id,
            [rule.model_dump() for rule in payload.rules],
        )
        db.commit()
        return ok(data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.put(
    "/process-routes/{route_id}/configuration",
    summary="原子保存路线步骤与内贸条件规则",
)
def put_process_route_configuration(
    route_id: int,
    payload: RouteConfigurationSaveRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("production:admin", "domestic:admin")),
):
    try:
        data = route_rule_service.save_route_configuration(
            db,
            route_id,
            [step.model_dump() for step in payload.steps],
            [rule.model_dump() for rule in payload.rules],
        )
        db.commit()
        return ok(data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


# ── 客户 ──────────────────────────────────────────────


@router.get("/customers", summary="内贸客户列表")
def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = Query(""),
    status: int | None = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_CUSTOMER_READ)),
):
    items, total = customer_service.list_customers(
        db, page=page, page_size=page_size, keyword=keyword, status=status
    )
    return ok(page_result(items, total, page, page_size))


@router.post("/customers", summary="新建客户")
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:write")),
):
    try:
        customer = customer_service.create_customer(db, payload, _uid(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok({"id": customer.id}, message="客户已创建")


@router.put("/customers/{customer_id}", summary="编辑客户")
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        customer_service.update_customer(db, customer_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已保存")


@router.delete("/customers/{customer_id}", summary="删除客户")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        customer_service.delete_customer(db, customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已删除")


@router.post("/customers/{customer_id}/recharges", summary="客户充值")
def recharge_customer(
    customer_id: int,
    payload: CustomerRechargeCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission("domestic:recharge", "domestic:admin")),
):
    try:
        data = balance_service.recharge_customer(
            db,
            customer_id=customer_id,
            amount=payload.amount,
            user_id=_uid(current_user),
            remark=payload.remark,
            request_id=payload.request_id,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        db.rollback()
        raise
    return ok(
        data,
        message=(
            "该笔充值已经处理过，当前会员状态以返回结果为准"
            if data["replayed"]
            else "充值成功"
        ),
    )


@router.get("/customers/{customer_id}/balance-ledger", summary="客户余额流水")
def list_customer_balance_ledger(
    customer_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission("domestic:recharge", "domestic:admin")),
):
    try:
        items, total = balance_service.list_customer_ledger(
            db, customer_id=customer_id, page=page, page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ok(page_result(items, total, page, page_size))


# ── 产品与工艺路线映射 ────────────────────────────────


@router.get("/products", summary="内贸产品列表（下单自动沉淀）")
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = Query(""),
    product_type: str = Query(""),
    route_bound: str = Query("", pattern="^(bound|unbound)?$"),
    price_status: str = Query("", pattern="^(configured|missing)?$"),
    sort_field: str = Query(""),
    sort_order: str = Query(""),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    items, total = product_service.list_products(
        db, page=page, page_size=page_size, keyword=keyword,
        product_type=product_type, route_bound=route_bound,
        price_status=price_status,
        sort_field=sort_field, sort_order=sort_order,
    )
    return ok(page_result(items, total, page, page_size))


@router.put("/products/{product_id}/base-price", summary="维护产品共享原始价格")
def put_product_base_price(
    product_id: int,
    payload: BasePriceUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        data = pricing_service.upsert_base_price(
            db,
            product_id=product_id,
            original_price=payload.original_price,
            user_id=_uid(current_user),
        )
        db.commit()
        return ok(data, message="原始价格已保存")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.delete("/products/{product_id}/base-price", summary="删除产品共享原始价格")
def delete_product_base_price(
    product_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        data = pricing_service.delete_base_price(db, product_id=product_id)
        db.commit()
        return ok(data, message="原始价格已删除")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/pricing/quote", summary="批量预览内贸会员报价")
def quote_product_prices(
    payload: PricingQuoteRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        data = pricing_service.quote_prices(db, payload)
        # attrs 报价会沉淀产品；即使缺价也必须让产品进入产品清单。
        db.commit()
        return ok(data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.put("/products/{product_id}/route", summary="人工改绑产品工艺路线")
def rebind_product_route(
    product_id: int,
    payload: ProductRouteRebind,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        product_service.rebind_product_route(db, product_id, payload.route_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已保存；仅对之后的新明细生效，在制明细保持下单时的路线")


@router.get("/craft-routes", summary="工艺→工艺路线映射列表")
def list_craft_routes(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    return ok(product_service.list_craft_routes(db))


@router.post("/craft-routes", summary="配置工艺→路线映射")
def upsert_craft_route(
    payload: CraftRouteUpsert,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        product_service.upsert_craft_route(
            db, product_type=payload.product_type, craft=payload.craft,
            route_id=payload.route_id, user_id=_uid(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="映射已保存，同工艺下未配路线的产品已自动补齐")


@router.delete("/craft-routes/{mapping_id}", summary="删除工艺映射")
def delete_craft_route(
    mapping_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        product_service.delete_craft_route(db, mapping_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已删除")


# ── 订单 ──────────────────────────────────────────────


@router.post("/orders", summary="内贸下单")
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:write")),
):
    try:
        data = order_service.create_order(db, payload, _uid(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    message = "草稿已保存" if data["is_draft"] else "下单成功"
    if data["warnings"]:
        message = ("草稿已保存" if data["is_draft"] else "下单成功") + "，但有明细暂时不能开工，见提示"
    return ok(data, message=message)


@router.get("/orders", summary="内贸订单列表")
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = Query(""),
    status: int | None = Query(None),
    customer_id: int | None = Query(None),
    order_category: str = Query("", pattern="^(normal|special)?$"),
    order_type: str = Query(""),
    order_channel: str = Query(""),
    date_start: date | None = Query(None),
    date_end: date | None = Query(None),
    sort_field: str = Query(""),
    sort_order: str = Query(""),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    items, total = order_service.list_orders(
        db, page=page, page_size=page_size, keyword=keyword, status=status,
        customer_id=customer_id, order_category=order_category,
        order_type=order_type, order_channel=order_channel,
        date_start=date_start, date_end=date_end,
        sort_field=sort_field, sort_order=sort_order,
    )
    return ok(page_result(items, total, page, page_size))


@router.get("/orders/{order_id}/export", summary="导出内贸订单领货单 Excel")
def export_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    try:
        data = order_service.get_order_detail(db, order_id)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    stream = export_service.build_order_workbook(data, data.get("created_by_name") or "")
    filename = quote(f"内贸订单-{data['domestic_no']}.xlsx")
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/orders/{order_id}", summary="订单详情（含逐明细工序进度）")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    try:
        data = order_service.get_order_detail(db, order_id)
        # 滚动发布期间旧实例可能写入 line_no=NULL；详情读取会在订单锁内补号，
        # 这里提交修复，避免每次请求都回滚后再次得到重复的 A1 标签。
        db.commit()
        return ok(data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/orders/{order_id}", summary="编辑订单头")
def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        order_service.update_order(db, order_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已保存")


@router.post("/orders/{order_id}/submit", summary="提交草稿并从客户余额扣款")
def submit_draft_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:write")),
):
    try:
        order = order_service.submit_draft(db, order_id, _uid(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok({
        "id": order.id,
        "status": order.status,
        "charged_amount": float(order.charged_amount or 0),
    }, message="订单已提交，余额扣款成功")


@router.post("/orders/{order_id}/status", summary="终止订单")
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        order_service.terminate_order(db, order_id, payload.reason, _uid(_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="订单已终止")


@router.delete("/orders/{order_id}", summary="删除订单（软删）")
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        order_service.delete_order(db, order_id, _uid(_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已删除")


# ── 明细 ──────────────────────────────────────────────


@router.post("/orders/{order_id}/items", summary="追加明细")
def add_item(
    order_id: int,
    payload: OrderItemAppend,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        data = order_service.add_item(db, order_id, payload, _uid(_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(data, message=data.get("warning") or "明细已添加")


@router.put("/items/{item_id}", summary="编辑明细")
def update_item(
    item_id: int,
    payload: OrderItemUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        order_service.update_item(db, item_id, payload, _uid(_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已保存")


@router.delete("/items/{item_id}", summary="删除明细")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        order_service.delete_item(db, item_id, _uid(_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="已删除")


@router.post("/items/{item_id}/attach-route", summary="给缺路线的明细补配工艺路线")
def attach_route(
    item_id: int,
    payload: ProductRouteRebind,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        data = order_service.attach_route(db, item_id, payload.route_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(data, message=f"已展开 {data['step_count']} 道工序，可以开工了")


@router.post("/items/{item_id}/ship", summary="登记发货（时间 + 克重）")
def ship_item(
    item_id: int,
    payload: ItemShipRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:write")),
):
    try:
        order_service.ship_item(db, item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(message="发货已登记")


@router.get("/items/{item_id}/progress", summary="明细工序进度（含每道可报数量）")
def get_item_progress(
    item_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    item = db.query(DomesticOrderItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="订单明细不存在")
    return ok({
        "item_id": item.id,
        "product_name": item.product_name,
        "order_qty": item.order_qty,
        "status": item.status,
        "steps": progress_service.build_progress_view(db, item),
    })


@router.get("/items/{item_id}/print-card", summary="流转卡打印数据（含二维码）")
def get_print_card(
    item_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    item = db.query(DomesticOrderItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="订单明细不存在")
    order = db.query(DomesticOrder).get(item.order_id)
    try:
        detail = order_service.get_order_detail(db, item.order_id)
    except ValueError as exc:  # 订单已软删
        raise HTTPException(status_code=404, detail=str(exc))
    item_view = next((i for i in detail["items"] if i["id"] == item_id), None)
    db.commit()

    qr_data = report_service.generate_qr_data(item_id)
    return ok({
        "item": item_view,
        "domestic_no": order.domestic_no,
        "order_no": order.order_no,
        "order_date": order.order_date,
        "customer_name": detail["customer_name"],
        "order_category": detail["order_category"],
        "order_category_label": detail["order_category_label"],
        "order_type": detail["order_type"],
        "order_type_label": detail["order_type_label"],
        "order_channel": detail["order_channel"],
        "order_channel_label": detail["order_channel_label"],
        "qr_data": qr_data,
        "qr_code_base64": _qr_png_base64(qr_data),
        "printed_at": beijing_now(),
    })


@router.get("/items/{item_id}/unit-qrcodes", summary="逐件二维码标签数据")
def get_item_unit_qrcodes(
    item_id: int,
    start_no: int = Query(1, ge=1),
    end_no: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    item = db.query(DomesticOrderItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="订单明细不存在")
    try:
        detail = order_service.get_order_detail(db, item.order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    last = min(end_no or item.order_qty, item.order_qty)
    if last < start_no:
        raise HTTPException(status_code=400, detail="结束序号不能小于开始序号")
    if last - start_no + 1 > 200:
        raise HTTPException(status_code=400, detail="单次最多生成 200 个逐件标签，请分段打印")
    units = unit_service.list_item_units(
        db, item=item, start_no=start_no, end_no=last,
    )
    # 正常情况迁移/下单时已建齐；这里的 commit 只是让滚动发布期间
    # 旧服务新建的明细在首次打标签时持久化补齐的单件行。
    db.commit()
    for unit in units:
        unit["qr_data"] = report_service.generate_unit_qr_data(unit["id"])
    item_view = next((row for row in detail["items"] if row["id"] == item.id), None)
    return ok({
        "item_id": item.id,
        "line_code": f"A{item.line_no or 1}",
        "product_name": item.product_name,
        "domestic_no": detail["domestic_no"],
        "order_qty": item.order_qty,
        "start_no": start_no,
        "end_no": last,
        "item": item_view,
        "units": units,
    })


@router.get("/items/{item_id}/wxacode", summary="订单进度小程序码（微信扫码免登录看完整订单）")
# 鉴权仍由函数参数 Depends(require_any_permission(*_READ)) 执行；这里只更新了端点摘要。
def get_item_wxacode(
    item_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    """生成指向小程序免登录进度页的小程序码（明细级，与流转卡同粒度），
    永久有效，可发客户/贴单据。

    生成失败（正式版未发布 / IP 白名单未配）时返回 502 并透传微信侧原因，
    不发出一张扫开是白屏的坏码。
    """
    from app.core.config import get_settings
    from app.mini import wx_client

    # 免登录端点的授权全押在这个签名密钥上，默认值 = 谁都能伪造，拒绝出码
    if report_service.qr_secret_is_default():
        raise HTTPException(
            status_code=503,
            detail="QR_SIGN_SECRET 还是仓库默认值，进度码已锁定——在 .env 配置随机密钥后重启",
        )

    item = db.query(DomesticOrderItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="订单明细不存在")
    order = db.query(DomesticOrder).filter(
        DomesticOrder.id == item.order_id, DomesticOrder.deleted_flag == 0
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == C.ORDER_DRAFT:
        raise HTTPException(status_code=400, detail="草稿订单提交后才能生成客户进度码")

    scene = report_service.generate_track_scene(item_id)
    try:
        image = wx_client.get_wxacode_base64(scene, page=C.TRACK_PAGE)
    except wx_client.WxApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return ok({
        "domestic_no": order.domestic_no,
        "order_no": order.order_no,
        "product_name": item.product_name,
        "order_qty": item.order_qty,
        "scene": scene,
        "image_base64": image,
        # trial 码只有体验成员能扫开，前端据此提醒「勿发客户」
        "env_version": get_settings().WX_MINI_ENV_VERSION or "release",
    })


def _qr_png_base64(qr_data: str) -> str | None:
    """二维码 PNG。qrcode 库缺失不该让整张卡打不出来，降级为只给文本。"""
    try:
        import qrcode

        img = qrcode.make(qr_data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:  # noqa: BLE001
        logger.warning("domestic qrcode render failed: %s", exc)
        print(f"[domestic] 二维码渲染失败，降级为纯文本: {exc}", flush=True)
        return None


# ── 报工（主站侧：查询 + 代报 + 撤销）──────────────────


@router.get("/reports", summary="报工流水查询")
def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user_id: int | None = Query(None),
    item_id: int | None = Query(None),
    date_start: datetime | None = Query(None),
    date_end: datetime | None = Query(None),
    include_revoked: bool = Query(True),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    items, total = report_service.list_reports(
        db, page=page, page_size=page_size, user_id=user_id, item_id=item_id,
        date_start=date_start, date_end=date_end, include_revoked=include_revoked,
    )
    return ok(page_result(items, total, page, page_size))


@router.get("/reports/skips", summary="人工跳过审计查询")
def list_manual_skip_audits(
    item_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        data = report_service.list_manual_skip_audits(db, item_id=item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ok(data)


@router.post("/reports", summary="主站代报工")
def submit_report(
    payload: ReportSubmit,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:write")),
):
    """跟单替车间录入。必须指明实际做活的工人 —— 件数记错人就等于工资算错人。"""
    try:
        data = report_service.submit_report(
            db, item_id=payload.item_id, progress_id=payload.progress_id,
            qty=payload.qty, user_id=_uid(current_user), source="web",
            request_id=payload.request_id,
            on_behalf_user_id=payload.on_behalf_user_id,
            outcomes=payload.outcomes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(data, message=f"已报 {payload.qty} 件")


@router.get("/process-workers", summary="某道工序有哪些工人（代报工选人用）")
def list_process_workers(
    process_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    rows = (
        db.query(ArkUser.id, ArkUser.real_name)
        .join(UserProcessBinding, UserProcessBinding.user_id == ArkUser.id)
        .filter(UserProcessBinding.process_id == process_id, ArkUser.is_active.is_(True))
        .order_by(ArkUser.real_name.asc())
        .all()
    )
    return ok([{"id": uid, "name": name} for uid, name in rows])


@router.post("/reports/revoke", summary="撤销报工")
def revoke_report(
    payload: ReportRevoke,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:write")),
):
    try:
        data = report_service.revoke_report(
            db, payload.log_id, _uid(current_user), is_admin=_has_admin(current_user)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(data, message="已撤销")


@router.post("/reports/skip", summary="主管人工跳过工序")
def submit_manual_skip(
    payload: ManualSkipSubmit,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        data = report_service.submit_manual_skip(
            db,
            item_id=payload.item_id,
            progress_id=payload.progress_id,
            qty=payload.qty,
            unit_id=payload.unit_id,
            reason=payload.reason,
            request_id=payload.request_id,
            user_id=_uid(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(data, message=f"已跳过 {data['skipped_qty']} 件")


@router.post("/reports/skip/{skip_log_id}/revoke", summary="撤销人工工序跳过")
def revoke_manual_skip(
    skip_log_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("domestic:admin")),
):
    try:
        data = report_service.revoke_manual_skip(
            db, skip_log_id, _uid(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(data, message="已撤销跳过")


@router.get("/reports/workload", summary="按人×工序的报工量汇总")
def workload_summary(
    date_start: datetime = Query(...),
    date_end: datetime = Query(...),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    return ok(report_service.get_workload_summary(db, date_start=date_start, date_end=date_end))


# ── 参考图 ────────────────────────────────────────────


@router.post("/images", summary="上传参考图")
async def upload_image(
    file: UploadFile = File(...),
    _user: dict = Depends(require_permission("domestic:write")),
):
    content = await file.read()
    try:
        file_service.validate_upload(file.filename, file.content_type or "", len(content))
        rel_path = file_service.store_bytes(file.filename, content)
    except file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok({"path": rel_path, "name": file.filename})


@router.get("/images/{rel_path:path}", summary="读取参考图")
def get_image(
    rel_path: str,
    _user: dict = Depends(require_any_permission(*_READ)),
):
    try:
        abs_path = file_service.resolve_path(rel_path)
    except file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(abs_path)
