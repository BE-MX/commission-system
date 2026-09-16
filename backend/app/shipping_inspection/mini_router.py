"""微信发货检验接口；挂载于 /api/mini，权限与主小程序入口一致。"""
import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.auth.models import ArkUser
from app.mini.access import require_mini_entry
from app.shipping_inspection import file_service as shipping_file_service
from app.shipping_inspection import outbound_service as shipping_outbound_service
from app.shipping_inspection import qr_service as shipping_qr_service
from app.shipping_inspection import service as shipping_service
from app.shipping_inspection.schemas import ShippingScanRequest, ShippingSubmitRequest
logger = logging.getLogger(__name__)
router = APIRouter()

# ── 发货检验 ──────────────────────────────────────────────
# 业务逻辑全在 app/shipping_inspection，这里只做薄路由。
# 所有接口由 mini_shipping:write 入口权限保护。

@router.post("/shipping-inspection/scan", summary="发货检验：扫出库单二维码")
async def shipping_scan(
    body: ShippingScanRequest,
    current_user: ArkUser = Depends(require_mini_entry("shipping")),
    db: Session = Depends(get_db),
):
    _ = current_user
    valid, record_id = shipping_qr_service.verify_qr_data(body.qr_raw)
    if not valid:
        raise HTTPException(
            status_code=400,
            detail={"code": "SIGN_INVALID", "message": "二维码无效，请扫描系统打印的出库单二维码"},
        )
    try:
        return shipping_service.scan_for_user(db, record_id, current_user.id, body.request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "RECORD_NOT_FOUND", "message": str(exc)})
    except shipping_outbound_service.OutboundTableError:
        logger.exception("shipping-inspection scan: 业务库出库表结构异常")
        raise HTTPException(
            status_code=500,
            detail={"code": "OUTBOUND_SOURCE_ERROR", "message": "出库单数据源异常，请联系管理员"},
        )


@router.post('/shipping-inspection/refresh', summary='发货检验：刷新当前单据（不记录扫码）')
async def shipping_refresh(body: ShippingScanRequest, current_user: ArkUser = Depends(require_mini_entry('shipping')), db: Session = Depends(get_db)):
    valid, record_id = shipping_qr_service.verify_qr_data(body.qr_raw)
    if not valid:
        raise HTTPException(400, detail={'message': '二维码无效'})
    try:
        return shipping_service.scan_payload(db, record_id)
    except ValueError as exc:
        raise HTTPException(400, detail={'message': str(exc)}) from exc


@router.post("/shipping-inspection/photos", summary="发货检验：上传验货照片（逐张）")
async def shipping_upload_photo(
    file: UploadFile = File(...),
    outbound_record_id: str = Form(...),
    item_id: str | None = Form(None),
    edit_version: int = Form(0, ge=0),
    current_user: ArkUser = Depends(require_mini_entry("shipping")),
    db: Session = Depends(get_db),
):
    return await _upload_media(file, outbound_record_id, item_id, edit_version, current_user, db, "image")


async def _upload_media(file, outbound_record_id, item_id, edit_version, current_user, db, media_type):
    rel_path = None
    try:
        if media_type == "video":
            rel_path = await shipping_file_service.store_video(file)
        else:
            content = await file.read(20 * 1024 * 1024 + 1)
            shipping_file_service.validate_upload(file.filename, file.content_type or "", len(content))
            rel_path = shipping_file_service.store_bytes(file.filename, content)
        photo = shipping_service.add_photo(
            db, outbound_record_id=outbound_record_id, item_id=item_id or None,
            file_path=rel_path, user_id=current_user.id, media_type=media_type, edit_version=edit_version,
        )
        return {"id": photo.id, "file_path": photo.file_path, "media_type": photo.media_type}
    except Exception as exc:
        db.rollback()
        if rel_path:
            # A commit response can be lost; never remove a file that is already referenced.
            from app.shipping_inspection.models import ShippingInspectionPhoto
            saved = db.query(ShippingInspectionPhoto.id).filter_by(file_path=rel_path).first()
            if saved is None:
                shipping_file_service.remove_file(rel_path)
        if isinstance(exc, shipping_file_service.FileValidationError):
            raise HTTPException(status_code=400, detail={"code": "BAD_FILE", "message": str(exc)}) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail={"code": "UPLOAD_REJECTED", "message": str(exc)}) from exc
        logger.warning("shipping media upload failed: %s", exc)
        print(f"[shipping_inspection] media upload failed: {exc}", flush=True)
        raise HTTPException(status_code=500, detail={"code": "UPLOAD_FAILED", "message": "上传未确认成功，请重新扫码核对后重试"}) from exc


@router.post("/shipping-inspection/videos", summary="发货检验：上传相册视频")
async def shipping_upload_video(
    file: UploadFile = File(...),
    outbound_record_id: str = Form(...),
    item_id: str | None = Form(None),
    edit_version: int = Form(0, ge=0),
    current_user: ArkUser = Depends(require_mini_entry("shipping")),
    db: Session = Depends(get_db),
):
    return await _upload_media(file, outbound_record_id, item_id, edit_version, current_user, db, "video")


@router.delete("/shipping-inspection/photos/{photo_id}", summary="发货检验：删除照片（仅提交前）")
async def shipping_delete_photo(
    photo_id: int,
    edit_version: int = Query(0, ge=0),
    current_user: ArkUser = Depends(require_mini_entry("shipping")),
    db: Session = Depends(get_db),
):
    try:
        shipping_service.delete_photo(db, photo_id, current_user.id, edit_version=edit_version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "DELETE_REJECTED", "message": str(exc)})
    return {"deleted": True}


@router.post("/shipping-inspection/submit", summary="发货检验：提交验货单")
async def shipping_submit(
    body: ShippingSubmitRequest,
    current_user: ArkUser = Depends(require_mini_entry("shipping")),
    db: Session = Depends(get_db),
):
    submitted_ids = []
    try:
        inspection = shipping_service.submit(
            db,
            outbound_record_id=body.outbound_record_id,
            user_id=current_user.id,
            remark=body.remark,
            edit_version=body.edit_version,
            submitted_ids=submitted_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "SUBMIT_REJECTED", "message": str(exc)})
    from app.shipping_inspection.notification_service import notify_submitted
    await notify_submitted(db, submitted_ids)
    return {
        "id": inspection.id,
        "outbound_record_id": inspection.outbound_record_id,
        "status": inspection.status,
        "photo_count": inspection.photo_count,
        "submitted_at": inspection.submitted_at.isoformat() if inspection.submitted_at else None,
    }


@router.get("/shipping-inspection/images/{rel_path:path}", summary="验货照片（小程序）")
async def shipping_image(
    rel_path: str,
    current_user: ArkUser = Depends(require_mini_entry("shipping")),
):
    """小程序 token 里没有 RBAC 声明，走不了主站那个 shipping_inspection:read 图片端点，
    所以这里给一个同源的 mini 版本——小程序显示缩略图用。"""
    _ = current_user
    try:
        abs_path = shipping_file_service.resolve_path(rel_path)
    except shipping_file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_PATH", "message": str(exc)})
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "图片不存在"})
    return FileResponse(abs_path)


@router.delete("/shipping-inspection/videos/{video_id}", summary="发货检验：删除视频（仅草稿）")
async def shipping_delete_video(
    video_id: int,
    edit_version: int = Query(0, ge=0),
    current_user: ArkUser = Depends(require_mini_entry("shipping")),
    db: Session = Depends(get_db),
):
    try:
        shipping_service.delete_photo(db, video_id, current_user.id, edit_version=edit_version, media_type="video")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "DELETE_REJECTED", "message": str(exc)}) from exc
    return {"deleted": True}
