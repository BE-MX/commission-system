"""半成品主数据、订单和库存 HTTP API。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.semifinished import service
from app.semifinished.schemas import (
    AllocationRecovery, InventoryAdjustment, MappingUpdate, OrderCreate, OrderStatusUpdate,
    QuoteRequest, ReceiptCreate,
)


router = APIRouter()


def _uid(user) -> int:
    if isinstance(user, dict):
        value = user.get("id") or user.get("user_id") or user.get("sub")
    else:
        value = getattr(user, "id", None)
    if value is None:
        raise HTTPException(401, "无法确认用户身份")
    return int(value)


@router.post("/materials/sync-preview")
def preview_material_sync(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:admin")),
):
    return ok(service.sync_preview(db))


@router.post("/materials/sync-apply")
def apply_material_sync(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:admin")),
):
    try:
        result = service.apply_sync(db)
    except Exception as exc:  # noqa: BLE001 - 同步失败必须回滚并给用户明确错误
        db.rollback()
        raise HTTPException(400, f"半成品同步失败：{exc}")
    return ok(result, message="半成品关联同步完成")


@router.get("/materials")
def get_materials(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    review_only: bool = Query(False),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:read")),
):
    result = service.list_materials(db, page, page_size, keyword, review_only)
    return ok(page_result(result["items"], result["total"], page, page_size))


@router.put("/mappings/{mapping_id}")
def confirm_mapping(
    mapping_id: int,
    body: MappingUpdate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:write")),
):
    try:
        result = service.update_mapping(db, mapping_id, [item.model_dump() for item in body.components])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(result, message="产品半成品配比已确认")


@router.get("/mappings")
def get_mappings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    review_only: bool = Query(False),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:read")),
):
    result = service.list_mappings(db, page, page_size, keyword, review_only)
    return ok(page_result(result["items"], result["total"], page, page_size))


@router.post("/quote")
def quote_product(
    body: QuoteRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("semifinished:read", "production:write", "invoice:write")),
):
    try:
        result = service.quote_product(db, body.product_id, body.finished_qty)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(result)


@router.post("/orders")
def create_order(
    body: OrderCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("semifinished:write")),
):
    try:
        order = service.create_order(
            db,
            items=[item.model_dump() for item in body.items],
            user_id=_uid(user),
            batch_no=body.batch_no,
            is_urgent=body.is_urgent,
            expected_delivery_date=body.expected_delivery_date,
            remark=body.remark,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    return ok({"id": order.id, "order_no": order.order_no}, message="半成品订单创建成功", code=201)


@router.get("/orders")
def get_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:read")),
):
    result = service.list_orders(db, page, page_size, status, keyword)
    return ok(page_result(result["items"], result["total"], page, page_size))


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:read")),
):
    result = service.get_order(db, order_id)
    if result is None:
        raise HTTPException(404, "半成品订单不存在")
    return ok(result)


@router.post("/order-items/{item_id}/receive")
def receive_order_item(
    item_id: int,
    body: ReceiptCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("semifinished:write")),
):
    try:
        result = service.receive_item(
            db,
            item_id=item_id,
            quantity_grams=body.quantity_grams,
            idempotency_key=body.idempotency_key,
            operator_id=_uid(user),
            remark=body.remark,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    return ok(result, message="半成品入库成功")


@router.put("/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    body: OrderStatusUpdate,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:write")),
):
    try:
        result = service.terminate_order(db, order_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(result, message="半成品订单已终止")


@router.get("/inventory")
def get_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:read")),
):
    result = service.list_inventory(db, page, page_size, keyword)
    return ok(page_result(result["items"], result["total"], page, page_size))


@router.get("/inventory/{material_id}/ledger")
def get_inventory_ledger(
    material_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("semifinished:read")),
):
    result = service.list_ledger(db, material_id, page, page_size)
    return ok(page_result(result["items"], result["total"], page, page_size))


@router.post("/inventory/{material_id}/adjust")
def adjust_inventory(
    material_id: int,
    body: InventoryAdjustment,
    db: Session = Depends(get_db),
    user=Depends(require_permission("semifinished:admin")),
):
    try:
        entry = service.adjust_inventory(
            db,
            material_id=material_id,
            quantity_grams=body.quantity_grams,
            idempotency_key=body.idempotency_key,
            remark=body.remark,
            operator_id=_uid(user),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    return ok({"ledger_id": entry.id}, message="库存调整成功")


@router.post("/inventory/reconcile-invoice/{invoice_id}")
def reconcile_invoice_inventory(
    invoice_id: int,
    body: AllocationRecovery,
    db: Session = Depends(get_db),
    user=Depends(require_permission("semifinished:admin")),
):
    try:
        result = service.recover_invoice_sync(db, invoice_id, body.action, _uid(user))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    return ok(result, message="发票半成品库存操作已恢复")
