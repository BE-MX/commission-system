"""物流跟踪 API 路由 (薄壳: 参数 / 权限 / 调用 service / 异常映射)"""

import logging
from datetime import date as _date_type

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Path, Query, UploadFile, status
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import ArkUser
from app.tracking.schemas import StagingCreateRequest, WaybillCreate
from app.tracking.staging_service import scan_staging
from app.tracking.polling_service import poll_active_shipments, refresh_single
from app.tracking.ocr_service import OCRParseError
from app.tracking import shipment_service, upload_service
from app.tracking.upload_service import WaybillConflict, OCR_TIMEOUT
from app.tracking.daily_report_service import (
    get_user_daily_report, generate_user_report, push_daily_report,
)

router = APIRouter()
logger = logging.getLogger("commission.tracking")


# ── 暂存 ─────────────────────────────────────────────────


@router.post("/staging", summary="运单推送到暂存表")
def create_staging(req: StagingCreateRequest, db: Session = Depends(get_db)):
    data = upload_service.create_staging(db, req)
    return {"code": 200, "message": "ok", "data": data}


# ── 查询 ─────────────────────────────────────────────────


@router.get("/shipments", summary="运单列表")
def list_shipments(
    status: str = Query("", description="状态筛选"),
    carrier: str = Query("", description="物流商筛选"),
    keyword: str = Query("", description="运单号/收件人模糊搜索"),
    is_active: str = Query("", description="是否活跃: 1/0"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_field: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    data = shipment_service.list_shipments(
        db, current_user,
        status=status, carrier=carrier, keyword=keyword,
        is_active=is_active, page=page, page_size=page_size,
        sort_field=sort_field, sort_order=sort_order,
    )
    return {"code": 200, "message": "ok", "data": data}


@router.get("/shipments/{waybill_no}", summary="运单详情+轨迹")
def get_shipment_detail(
    waybill_no: str = Path(...),
    db: Session = Depends(get_db),
):
    detail = shipment_service.get_shipment_detail(db, waybill_no)
    if detail is None:
        return {"code": 404, "message": f"运单 {waybill_no} 不存在", "data": None}
    return {"code": 200, "message": "ok", "data": detail}


@router.delete("/shipments/{waybill_no}", summary="删除运单（软删除）")
def delete_shipment(
    waybill_no: str = Path(...),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("tracking:delete")),
):
    from app.tracking.models import ShipmentTracking
    shipment = db.query(ShipmentTracking).filter(ShipmentTracking.waybill_no == waybill_no).first()
    if not shipment:
        raise HTTPException(status_code=404, detail=f"运单 {waybill_no} 不存在")
    shipment.is_active = False
    db.commit()
    return {"code": 200, "message": "已删除", "data": None}


@router.post("/shipments/{waybill_no}/refresh", summary="手动刷新运单状态")
async def refresh_shipment(
    waybill_no: str = Path(...),
    db: Session = Depends(get_db),
):
    result = await refresh_single(db, waybill_no)
    if "error" in result:
        return {"code": 404, "message": result["error"], "data": None}
    return {"code": 200, "message": "ok", "data": result}


@router.get("/stats", summary="统计概览")
def get_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return {"code": 200, "message": "ok", "data": shipment_service.get_stats(db, current_user)}


@router.get("/submitters", summary="提交人列表（用于前端下拉筛选）")
def list_submitters(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("tracking:read")),
):
    return {"code": 200, "message": "ok", "data": shipment_service.list_submitters(db)}


# ── 定时任务触发 ─────────────────────────────────────────


@router.post("/poll", summary="批量轮询（定时任务调用）")
async def trigger_poll(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("tracking:read")),
):
    stats = await poll_active_shipments(db)
    return {"code": 200, "message": "ok", "data": stats}


@router.post("/scan-staging", summary="扫描暂存表（定时任务调用）")
async def trigger_scan(db: Session = Depends(get_db)):
    stats = await scan_staging(db)
    return {"code": 200, "message": "ok", "data": stats}


# ══════════════════════════════════════════════════════════════
#  运单上传(图片 OCR + 手动录入)
# ══════════════════════════════════════════════════════════════


@router.post("/upload-ocr", summary="上传运单图片并 OCR 识别")
async def upload_ocr(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_permission("tracking:write")),
):
    # 校验 MIME / 大小
    contents = await file.read()
    try:
        suffix = upload_service.validate_upload_file(
            file.content_type, len(contents), file.filename
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": 422, "message": str(exc), "data": None},
        )

    try:
        data = await upload_service.run_ocr(contents, suffix)
        message = "识别成功" if data["ocr_confidence"] != "failed" else "未能识别运单信息"
        return {"code": 200, "message": message, "data": data}
    except HTTPException:
        raise
    except __import__("asyncio").TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": 504, "message": f"AI 识别超时（超过{OCR_TIMEOUT}秒），请重试", "data": None},
        )
    except OCRParseError as exc:
        logger.error("OCR 解析失败: %s | raw=%s", exc, getattr(exc, "raw_text", "")[:500])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": 502,
                "message": f"AI 识别结果解析失败: {exc}，请确认图片是运单后重试，或切换手动录入",
                "data": None,
            },
        )
    except Exception as exc:
        logger.exception("OCR 调用异常: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": 502, "message": "AI 识别服务暂时不可用，请稍后重试或手动录入", "data": None},
        )


@router.get("/waybills/check", summary="运单号去重检查")
def check_waybill(
    waybill_no: str = Query(..., min_length=1, max_length=50),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("tracking:write")),
):
    existing = upload_service.check_waybill_exists(db, waybill_no)
    if existing is None:
        return {"code": 200, "exists": False, "data": None}
    return {"code": 200, "exists": True, "data": existing}


@router.post("/waybills", status_code=status.HTTP_201_CREATED, summary="提交运单入库")
async def create_waybill(
    payload: WaybillCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("tracking:write")),
):
    try:
        data = await upload_service.create_waybill_with_tracking(db, payload, current_user)
    except WaybillConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": 409, "message": "运单号已存在", "data": exc.existing},
        )
    except IntegrityError as exc:
        db.rollback()
        logger.warning("运单入库唯一约束冲突: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": 409, "message": "运单号已存在", "data": None},
        )
    except ProgrammingError as exc:
        db.rollback()
        logger.exception("运单入库数据库错误: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": 500, "message": "数据库结构错误，请联系管理员", "data": None},
        )
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("运单入库失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": 500, "message": "数据库写入失败，请稍后重试", "data": None},
        )

    return {"code": 201, "message": "运单录入成功", "data": data}


# ══════════════════════════════════════════════════════════════
#  物流日报
# ══════════════════════════════════════════════════════════════


def _parse_report_date(report_date: str | None):
    """解析日报日期参数,失败抛 ValueError。None / 空字符串 → 今天。"""
    if not report_date:
        return _date_type.today()
    return _date_type.fromisoformat(report_date)


@router.get("/daily-report", summary="获取物流日报")
def get_daily_report(
    report_date: str = Query(None, description="日报日期 YYYY-MM-DD，默认今天"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取当前用户指定日期的物流日报 HTML 内容。"""
    user_id = current_user.get("sub")
    if not user_id:
        return {"code": 401, "message": "未登录", "data": None}

    try:
        target_date = _parse_report_date(report_date)
    except ValueError:
        return {"code": 400, "message": "日期格式错误，应为 YYYY-MM-DD", "data": None}

    report = get_user_daily_report(db, int(user_id), target_date)
    if not report:
        return {
            "code": 200,
            "message": "ok",
            "data": {"exists": False, "html": None, "report_date": target_date.isoformat()},
        }
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "exists": True,
            "html": report.html_content,
            "report_date": report.report_date.isoformat(),
            "short_url": report.short_url,
            "is_pushed": report.is_pushed,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        },
    }


@router.post("/daily-report/generate", summary="手动生成物流日报")
def generate_daily_report(
    background_tasks: BackgroundTasks,
    report_date: str = Query(None, description="日报日期 YYYY-MM-DD，默认今天"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """手动生成当前用户指定日期的物流日报。"""
    user_id = current_user.get("sub")
    if not user_id:
        return {"code": 401, "message": "未登录", "data": None}

    try:
        target_date = _parse_report_date(report_date)
    except ValueError:
        return {"code": 400, "message": "日期格式错误，应为 YYYY-MM-DD", "data": None}

    user = db.query(ArkUser).filter(ArkUser.id == int(user_id)).first()
    if not user:
        return {"code": 400, "message": "用户不存在", "data": None}

    try:
        report = generate_user_report(
            db, int(user_id), user.dingtalk_id or "", target_date, username=user.username
        )
        if not report:
            return {"code": 200, "message": "ok", "data": {"exists": False, "reason": "无运单数据"}}

        background_tasks.add_task(push_daily_report, db, report)

        return {
            "code": 200,
            "message": "日报已生成",
            "data": {
                "exists": True,
                "html": report.html_content,
                "report_date": report.report_date.isoformat(),
                "short_url": report.short_url,
                "is_pushed": report.is_pushed,
                "created_at": report.created_at.isoformat() if report.created_at else None,
            },
        }
    except Exception as e:
        logger.exception("手动生成日报失败: %s", e)
        return {"code": 500, "message": f"生成失败: {e}", "data": None}
