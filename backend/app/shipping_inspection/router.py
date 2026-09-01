"""发货检验 — PC 端 API 路由

权限：shipping_inspection:read（查看）/ shipping_inspection:write / shipping_inspection:admin，
读接口任一即可。统一信封 ok()；业务库（lsordertest）只读。
"""

import base64
import io
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.shipping_inspection import constants as C
from app.shipping_inspection import file_service, outbound_service, qr_service, service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto

logger = logging.getLogger("commission")

router = APIRouter()

_READ = ("shipping_inspection:read", "shipping_inspection:write", "shipping_inspection:admin")


def _qr_png_base64(qr_data: str) -> str | None:
    """二维码 PNG。qrcode 库缺失不该让整张出库单打不出来，降级为只给文本。"""
    try:
        import qrcode

        img = qrcode.make(qr_data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:  # noqa: BLE001
        logger.warning("shipping_inspection qrcode render failed: %s", exc)
        print(f"[shipping_inspection] 二维码渲染失败，降级为纯文本: {exc}", flush=True)
        return None


# ── 出库单（业务库只读）────────────────────────────────────


@router.get("/outbound-records", summary="出库单分页列表（含检验状态）")
def list_outbound_records(
    keyword: str | None = Query(None, description="匹配出库单号/客户"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    try:
        rows, total = outbound_service.list_outbound_records(
            db, keyword=keyword, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
        )
    except outbound_service.OutboundTableError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # 检验状态按 outbound_record_id 批量查自有表组装：none=未验 / draft / submitted
    record_ids = [row["outbound_record_id"] for row in rows]
    status_map: dict[str, ShippingInspection] = {}
    if record_ids:
        inspections = (
            db.query(ShippingInspection)
            .filter(ShippingInspection.outbound_record_id.in_(record_ids))
            .all()
        )
        status_map = {insp.outbound_record_id: insp for insp in inspections}
    # draft 单的 photo_count 只在提交时回写，列表改按实时计数，避免"已传 3 张仍显示 0"
    draft_ids = [insp.id for insp in status_map.values() if insp.status == C.STATUS_DRAFT]
    draft_counts: dict[int, int] = {}
    if draft_ids:
        draft_counts = dict(
            db.query(ShippingInspectionPhoto.inspection_id, func.count(ShippingInspectionPhoto.id))
            .filter(ShippingInspectionPhoto.inspection_id.in_(draft_ids))
            .group_by(ShippingInspectionPhoto.inspection_id)
            .all()
        )
    for row in rows:
        insp = status_map.get(row["outbound_record_id"])
        row["status"] = insp.status if insp else "none"
        if insp is None:
            row["photo_count"] = 0
        elif insp.status == C.STATUS_DRAFT:
            row["photo_count"] = draft_counts.get(insp.id, 0)
        else:
            row["photo_count"] = insp.photo_count
    return ok(page_result(rows, total, page, page_size))


@router.get("/outbound-records/{record_id}/print-data", summary="出库单打印数据（单头+明细+二维码）")
def outbound_print_data(
    record_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    try:
        record = outbound_service.get_outbound_record(db, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="出库单不存在")
        items = outbound_service.list_outbound_items(db, record_id)
    except outbound_service.OutboundTableError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    qr_data = qr_service.generate_qr_data(record_id)
    return ok({
        "record": record,
        "items": items,
        "qr_data": qr_data,
        "qr_code_base64": _qr_png_base64(qr_data),
    })


# ── 验货单（自有库）──────────────────────────────────────


@router.get("/records", summary="已提交验货单分页列表")
def list_records(
    keyword: str | None = Query(None, description="匹配出库单号/客户"),
    date_from: date | None = Query(None, description="提交日期起"),
    date_to: date | None = Query(None, description="提交日期止"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    items, total = service.list_records(
        db, keyword=keyword, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
    )
    return ok(page_result(items, total, page, page_size))


@router.get("/records/{inspection_id}", summary="验货单详情（单头+明细+照片）")
def record_detail(
    inspection_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    detail = service.get_record_detail(db, inspection_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="验货单不存在")
    return ok(detail)


# ── 照片读取 ─────────────────────────────────────────────


@router.get("/images/{rel_path:path}", summary="读取验货照片")
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
