"""发货检验 — PC 端 API 路由

权限：shipping_inspection:read（查看）/ shipping_inspection:write / shipping_inspection:admin，
读接口任一即可。出库单（列表 + 打印数据）按本地方舟首推订单业务员或既有
OKKI 镜像客户归属过滤；shipping_inspection:read_all 或 super_admin 看全部。
统一信封 ok()；业务库（lsordertest）只读。
"""

import base64
import io
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.responses import Response
from urllib.parse import quote
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.auth.models import ArkUserExternalBinding
from app.core.database import get_db
from app.core.response import ok, page_result
from app.shipping_inspection import constants as C
from app.shipping_inspection import file_service, outbound_service, outbound_queue_service, qr_service, service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto
from app.shipping_inspection.schemas import ShippingRecallRequest
from app.shipping_inspection.print_customer_service import with_customer_order_info
from app.shipping_inspection.print_service import with_owner_chinese_name

logger = logging.getLogger("commission")

router = APIRouter()
from app.shipping_inspection.station_router import router as station_router
router.include_router(station_router)
from app.shipping_inspection.outbound_sync_router import router as outbound_sync_router
router.include_router(outbound_sync_router)

_READ = ("shipping_inspection:read", "shipping_inspection:write", "shipping_inspection:admin")


def _outbound_scope(db: Session, user: dict, read_all_permission: str = "shipping_inspection:read_all") -> str | None:
    """出库单数据范围：看全部返回 None；否则返回当前用户绑定的 OKKI 业务员 id。

    解析模式与 order_intelligence.resolve_scope 一致：active OKKI 绑定、primary 优先。
    """
    if "super_admin" in (user.get("roles") or []):
        return None
    if read_all_permission in (user.get("permissions") or []):
        return None
    try:
        ark_user_id = int(user.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录用户信息无效") from None
    binding = (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.ark_user_id == ark_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .order_by(ArkUserExternalBinding.is_primary.desc(), ArkUserExternalBinding.id)
        .first()
    )
    okki_user_id = str(binding.external_account_id).strip() if binding and binding.external_account_id else ""
    if not okki_user_id:
        raise HTTPException(status_code=422, detail="当前账号尚未绑定 OKKI 业务员，请联系管理员配置")
    return okki_user_id


def _inspection_scope(db: Session, user: dict) -> str | None:
    return _outbound_scope(db, user, "shipping_inspection:inspection_read_all")


def _require_inspection_scope(db: Session, user: dict, inspection_id: int):
    scope = _inspection_scope(db, user)
    inspection = db.get(ShippingInspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=404, detail="验货单不存在")
    if scope is not None:
        try:
            record = outbound_service.get_outbound_record(db, inspection.outbound_record_id, okki_user_id=scope, include_deleted=True)
        except outbound_service.OutboundTableError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="验货单不存在")
    return inspection


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


@router.delete('/outbound-records/{record_id}', summary='删除小满待出库单并同步方舟显示')
def delete_outbound_record(
    record_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission('shipping_inspection:delete')),
):
    from app.shipping_inspection import outbound_delete_service as deletion
    from app.shipping_inspection.outbound_delete_client import DeleteRemoteError
    from app.invoice.okki_client import OkkiApiError
    scope = _outbound_scope(db, user)
    record = outbound_service.get_outbound_record(db, record_id, okki_user_id=scope, include_deleted=True)
    if record is None:
        # A normal mirror sync may remove the header after an ambiguous POST.
        # Only the original actor or an all-scope deleter can recover that intent.
        from app.shipping_inspection.models import ShippingOperationEvent
        event = db.query(ShippingOperationEvent).filter_by(
            scope=deletion.SCOPE, outbound_record_id=record_id,
        ).first()
        if event is None or (scope is not None and event.login_user_id != int(user['sub'])):
            raise HTTPException(404, '出库单不存在')
        if event.action not in (deletion.PENDING, deletion.UNCERTAIN, deletion.DELETED):
            raise HTTPException(404, '出库单不存在')
        record = {'outbound_record_id': record_id, 'outbound_invoice_id': event.request_id,
                  'outbound_no': event.payload['outbound_no']}
    try:
        return ok(deletion.delete_outbound(db, record, int(user['sub'])))
    except (deletion.OutboundDeleteError, DeleteRemoteError, OkkiApiError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc


@router.get("/outbound-records", summary="出库单分页列表（含检验状态）")
def list_outbound_records(
    keyword: str | None = Query(None, description="匹配出库单号/客户"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*_READ)),
):
    scope_okki_user = _outbound_scope(db, user)
    try:
        rows, total = outbound_queue_service.list_outbound_records(
            db, keyword=keyword, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
            okki_user_id=scope_okki_user,
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
            .filter(ShippingInspectionPhoto.inspection_id.in_(draft_ids), ShippingInspectionPhoto.media_type == "image")
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
    user: dict = Depends(require_any_permission(*_READ)),
):
    scope_okki_user = _outbound_scope(db, user)
    try:
        # 归属过滤并入查询：不可见与不存在统一 404，不泄露单号是否存在
        record = outbound_service.get_outbound_record(db, record_id, okki_user_id=scope_okki_user)
        if record is None:
            raise HTTPException(status_code=404, detail="出库单不存在")
        from app.shipping_inspection.outbound_sync_state import ensure_printable, apply_header
        sync_event = ensure_printable(db, record_id)
        record = apply_header(db, record, event=sync_event)
        items = outbound_service.list_outbound_items(db, record_id, sync_event=sync_event)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except outbound_service.OutboundTableError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    from app.shipping_inspection.print_service import annotate_print_items, sort_outbound_print_items
    items = sort_outbound_print_items(annotate_print_items(db, items))
    qr_data = qr_service.generate_qr_data(record_id)
    return ok({
        "record": with_customer_order_info(db, with_owner_chinese_name(db, record)),
        "items": items,
        "qr_data": qr_data,
        "qr_code_base64": _qr_png_base64(qr_data),
    })


# ── 验货单（自有库）──────────────────────────────────────


@router.get("/outbound-records/{record_id}/word", summary="下载出库单 Word（与打印版式一致）")
def outbound_word(
    record_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*_READ)),
):
    from app.shipping_inspection.print_service import annotate_print_items
    from app.shipping_inspection.word_service import build_outbound_word
    scope = _outbound_scope(db, user)
    try:
        record = outbound_service.get_outbound_record(db, record_id, okki_user_id=scope)
        if record is None:
            raise HTTPException(status_code=404, detail="出库单不存在")
        from app.shipping_inspection.outbound_sync_state import ensure_printable, apply_header
        sync_event = ensure_printable(db, record_id)
        record = apply_header(db, record, event=sync_event)
        items = outbound_service.list_outbound_items(db, record_id, sync_event=sync_event)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except outbound_service.OutboundTableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    content = build_outbound_word(
        with_customer_order_info(db, with_owner_chinese_name(db, record)),
        annotate_print_items(db, items),
        qr_service.generate_qr_data(record_id),
    )
    filename = quote(f"出库单-{record['outbound_no']}.docx", safe="")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@router.post("/records/{inspection_id}/recall", summary="撤回验货单编辑（保留已上传媒体）")
def recall_record(
    inspection_id: int,
    body: ShippingRecallRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission("shipping_inspection:write", "shipping_inspection:admin")),
):
    _require_inspection_scope(db, user, inspection_id)
    try:
        inspection = service.recall(db, inspection_id, int(user["sub"]), body.edit_version)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok({"id": inspection.id, "status": inspection.status, "edit_version": inspection.edit_version})


@router.get("/records", summary="已提交验货单分页列表")
def list_records(
    keyword: str | None = Query(None, description="匹配出库单号/客户"),
    salesperson_name: str | None = Query(None, max_length=100, description="关联订单业务员姓名"),
    submitted_by_name: str | None = Query(None, max_length=100, description="提交检验人员姓名"),
    date_from: date | None = Query(None, description="提交日期起"),
    date_to: date | None = Query(None, description="提交日期止"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="提交日期起不能晚于提交日期止")
    scope = _inspection_scope(db, _user)
    try:
        items, total = service.list_records(
            db, keyword=keyword, submitted_by_name=submitted_by_name, salesperson_name=salesperson_name, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
            okki_user_id=scope,
        )
    except outbound_service.OutboundTableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ok(page_result(items, total, page, page_size))


@router.get("/records/{inspection_id}/pdf", summary="下载已提交验货单 PDF（含照片）")
def inspection_pdf(
    inspection_id: int,
    edit_version: int | None = Query(None, ge=0),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*_READ)),
):
    from app.shipping_inspection.pdf_service import export_inspection_pdf
    _require_inspection_scope(db, user, inspection_id)
    content, outbound_no = export_inspection_pdf(db, inspection_id, edit_version)
    filename = quote(f"验货单-{outbound_no}.pdf", safe="")
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "Cache-Control": "no-store",
    })


@router.get("/records/{inspection_id}", summary="验货单详情（单头+明细+照片）")
def record_detail(
    inspection_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    _require_inspection_scope(db, _user, inspection_id)
    detail = service.get_record_detail(db, inspection_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="验货单不存在")
    from app.auth.service import get_live_user_authorization
    from app.shipping_inspection.audit_service import list_events
    roles, permissions = get_live_user_authorization(db, int(_user['sub']))
    detail['events'] = list_events(db, detail['outbound_record_id'], include_login='super_admin' in roles or 'shipping_inspection:admin' in permissions)
    return ok(detail)


# ── 照片读取 ─────────────────────────────────────────────


@router.get("/images/{rel_path:path}", summary="读取验货照片")
def get_image(
    rel_path: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_any_permission(*_READ)),
):
    try:
        abs_path = file_service.resolve_path(rel_path)
    except file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    photo = db.query(ShippingInspectionPhoto).filter(ShippingInspectionPhoto.file_path == rel_path).first()
    if photo is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    _require_inspection_scope(db, _user, photo.inspection_id)
    record = service.transfers.snapshot(db, 'shipping-inspection', photo.file_path)
    db.rollback()
    return service.transfers.response('shipping-inspection', rel_path, record)


from pydantic import BaseModel, Field


class DeleteRecovery(BaseModel):
    reason: str = Field(min_length=10, max_length=500)
    confirmed: bool


@router.post('/outbound-records/{record_id}/delete-recovery', summary='人工终止待核对删除，保留远端出库单')
def recover_outbound_delete(record_id: str, body: DeleteRecovery, db: Session = Depends(get_db),
                            user: dict = Depends(require_permission('shipping_inspection:admin'))):
    from app.shipping_inspection import outbound_delete_service as deletion
    from app.shipping_inspection.outbound_delete_client import DeleteRemoteError
    from app.invoice.okki_client import OkkiApiError
    record = outbound_service.get_outbound_record(db, record_id, okki_user_id=_outbound_scope(db, user), include_deleted=True)
    if record is None:
        raise HTTPException(404, '请使用原删除入口核对已消失的出库单')
    if not body.confirmed:
        raise HTTPException(400, '请确认已核实小满原单')
    try:
        return ok(deletion.abandon_pending(db, record, int(user['sub']), body.reason.strip()))
    except (ValueError, DeleteRemoteError, OkkiApiError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
