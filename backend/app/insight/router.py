"""方舟洞见 — API 路由"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import get_current_user, require_permission
from app.insight import service
from app.insight.schemas import (
    CaseManualCreate,
    CasePublish,
    MinutesUpload,
    ReportImport,
    SourceCreate,
    SourceUpdate,
    TaskUpdate,
)

logger = logging.getLogger("insight")
router = APIRouter()

INTERNAL_REPORT_TYPES = {"shop_analysis", "competitor_analysis", "inquiry_analysis"}


def _ok(data, message: str = "ok"):
    return {"code": 200, "message": message, "data": data}


def _is_super_admin(user: dict) -> bool:
    return "super_admin" in (user.get("roles") or [])


def _has_perm(user: dict, code: str) -> bool:
    if _is_super_admin(user):
        return True
    return code in (user.get("permissions") or [])


def _has_any_perm(user: dict, codes: list[str]) -> bool:
    if _is_super_admin(user):
        return True
    perms = set(user.get("permissions") or [])
    return any(c in perms for c in codes)


def _require_insight_view(user: dict = Depends(get_current_user)):
    """统一基础查看权限:任意 insight:* 都可读普通报告。"""
    if not _has_any_perm(user, ["insight:read", "insight:write", "insight:internal_read", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight 任一权限")
    return user


def _require_insight_internal(user: dict = Depends(get_current_user)):
    """内部经营报告查看:internal_read 或 admin。"""
    if not _has_any_perm(user, ["insight:internal_read", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:internal_read")
    return user


def _require_insight_admin(user: dict = Depends(get_current_user)):
    if not _has_perm(user, "insight:admin"):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:admin")
    return user


def _verify_import_api_key(authorization: Optional[str] = Header(None)):
    """ACCIO WORK 等外部系统使用 Bearer API Key 认证。"""
    expected = os.environ.get("INSIGHT_IMPORT_API_KEY", "").strip()
    if not expected:
        # 未配置时拒绝所有外部导入,防误用
        raise HTTPException(status_code=503, detail="导入接口未启用(INSIGHT_IMPORT_API_KEY 未配置)")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="API Key 无效")
    return True


# ──────────────────────────────────────────────────────
# 报告(Reports)
# ──────────────────────────────────────────────────────

@router.get("/reports")
def list_reports(
    report_type: Optional[str] = Query(None, description="支持逗号分隔多个类型"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    # 内部类型权限校验
    if report_type:
        types = {t.strip() for t in report_type.split(",") if t.strip()}
        internal = types & INTERNAL_REPORT_TYPES
        if internal and not _has_any_perm(user, ["insight:internal_read", "insight:admin"]):
            raise HTTPException(status_code=403, detail="无权查看内部经营报告")
    result = service.list_reports(
        db,
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        status=status,
        page=page,
        page_size=page_size,
    )
    return _ok(result)


@router.get("/reports/{report_id}")
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    r = service.get_report(db, report_id)
    if r.report_type in INTERNAL_REPORT_TYPES and not _has_any_perm(user, ["insight:internal_read", "insight:admin"]):
        raise HTTPException(status_code=403, detail="无权查看内部经营报告")
    return _ok({
        "id": r.id,
        "report_type": r.report_type,
        "report_date": r.report_date.isoformat() if r.report_date else None,
        "title": r.title,
        "status": r.status,
        "report_metadata": r.report_metadata,
        "error_msg": r.error_msg,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "source_data": r.source_data,
    })


@router.get("/reports/{report_id}/html")
def get_report_html(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    r = service.get_report(db, report_id)
    if r.report_type in INTERNAL_REPORT_TYPES and not _has_any_perm(user, ["insight:internal_read", "insight:admin"]):
        raise HTTPException(status_code=403, detail="无权查看内部经营报告")
    try:
        html = service.get_report_html(db, report_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.post("/reports/{report_id}/regenerate")
def regenerate_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    user_id = int(user.get("sub")) if user.get("sub") else None
    r = service.regenerate_report(db, report_id, user_id)
    return _ok({"id": r.id, "status": r.status}, "已触发重新生成(信源抓取暂未实现,待后续接入)")


@router.post("/reports/import")
def import_report(
    data: ReportImport,
    db: Session = Depends(get_db),
    _: bool = Depends(_verify_import_api_key),
):
    r = service.import_report(db, data)
    return _ok({"id": r.id, "status": r.status, "report_date": r.report_date.isoformat()}, "导入成功")


# ──────────────────────────────────────────────────────
# 信源(Sources)
# ──────────────────────────────────────────────────────

@router.get("/sources")
def list_sources(
    source_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    pipeline: Optional[str] = None,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    rows = service.list_sources(db, source_type=source_type, is_active=is_active, pipeline=pipeline)
    return _ok([_serialize_source(s) for s in rows])


@router.get("/sources/{source_id}")
def get_source(
    source_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    s = service.get_source(db, source_id)
    return _ok(_serialize_source(s))


@router.post("/sources")
def create_source(
    data: SourceCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    s = service.create_source(db, data)
    return _ok(_serialize_source(s), "创建成功")


@router.put("/sources/{source_id}")
def update_source(
    source_id: int,
    data: SourceUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    s = service.update_source(db, source_id, data)
    return _ok(_serialize_source(s), "更新成功")


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    service.delete_source(db, source_id)
    return _ok(None, "已禁用")


@router.post("/sources/{source_id}/test")
def test_source(
    source_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    result = service.test_source(db, source_id)
    return _ok(result)


def _serialize_source(s):
    return {
        "id": s.id,
        "name": s.name,
        "source_type": s.source_type,
        "url": s.url,
        "keywords": s.keywords,
        "css_selector": s.css_selector,
        "request_headers": s.request_headers,
        "fetch_interval_hours": s.fetch_interval_hours,
        "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        "last_error": s.last_error,
        "consecutive_failures": s.consecutive_failures,
        "is_active": bool(s.is_active),
        "pipeline": s.pipeline,
        "sort_order": s.sort_order,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


# ──────────────────────────────────────────────────────
# 案例库(Cases)
# ──────────────────────────────────────────────────────

@router.post("/cases/upload")
async def upload_case(
    source_type: str = Form(...),
    text: Optional[str] = Form(None),
    share_person: Optional[str] = Form(None),
    share_date: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not _has_any_perm(user, ["insight:write", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:write")

    user_id = int(user.get("sub"))
    user_name = user.get("username", "")

    file_path = None
    if source_type == "screenshot":
        if not file:
            raise HTTPException(status_code=400, detail="screenshot 模式需要上传文件")
        file_path = service._save_uploaded_image(file.file, file.filename or "upload.png")
    elif source_type == "text_paste":
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="text_paste 模式需要传入 text")
    else:
        raise HTTPException(status_code=400, detail="非法的 source_type")

    sd = None
    if share_date:
        try:
            sd = date.fromisoformat(share_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="share_date 格式应为 YYYY-MM-DD")

    case = service.upload_case(
        db,
        user_id=user_id,
        user_name=user_name,
        source_type=source_type,
        text=text,
        file_path=file_path,
        share_person=share_person,
        share_date=sd,
    )
    return _ok({"case_id": case.id, "status": case.status, "error_msg": case.error_msg}, "上传成功")


@router.post("/cases/manual")
def manual_create_case(
    data: CaseManualCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not _has_any_perm(user, ["insight:write", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:write")
    user_id = int(user.get("sub"))
    case = service.manual_create_case(db, user_id=user_id, user_name=user.get("username", ""), data=data)
    return _ok(_serialize_case(case, user_id), "发布成功")


@router.get("/cases/{case_id}/status")
def get_case_status(
    case_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    return _ok(service.get_case_status(db, case_id))


@router.post("/cases/{case_id}/publish")
def publish_case(
    case_id: int,
    data: CasePublish,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not _has_any_perm(user, ["insight:write", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:write")
    user_id = int(user.get("sub"))
    case = service.publish_case(db, case_id, user_id, data)
    return _ok(_serialize_case(case, user_id), "已发布")


@router.get("/cases")
def list_cases(
    share_person: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    product_type: Optional[str] = None,
    market: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = Query("date", regex="^(date|likes)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    user_id = int(user.get("sub")) if user.get("sub") else None
    result = service.list_cases(
        db,
        share_person=share_person,
        start_date=start_date,
        end_date=end_date,
        product_type=product_type,
        market=market,
        tag=tag,
        q=q,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    items = [_serialize_case(c, user_id) for c in result["items"]]
    return _ok({"total": result["total"], "items": items})


@router.get("/cases/{case_id}")
def get_case_detail(
    case_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    user_id = int(user.get("sub")) if user.get("sub") else None
    case = service.get_case_detail(db, case_id, user_id)
    return _ok(_serialize_case(case, user_id))


@router.delete("/cases/{case_id}")
def delete_case(
    case_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not _has_any_perm(user, ["insight:write", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:write")
    user_id = int(user.get("sub"))
    is_admin = _has_perm(user, "insight:admin")
    service.delete_case(db, case_id, user_id, is_admin=is_admin)
    return _ok(None, "已归档")


@router.post("/cases/{case_id}/like")
def toggle_like(
    case_id: int,
    delta: int = Query(1),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    if delta not in (1, -1):
        raise HTTPException(status_code=400, detail="delta 必须为 1 或 -1")
    new_count = service.toggle_case_like(db, case_id, delta)
    return _ok({"case_id": case_id, "like_count": new_count})


def _serialize_case(c, current_user_id: Optional[int] = None):
    return {
        "id": c.id,
        "title": c.title,
        "scenario": c.scenario,
        "what_was_done": c.what_was_done,
        "result": c.result,
        "customer_name": c.customer_name,
        "tags": c.tags or [],
        "attachments": c.attachments or [],
        "highlights": c.highlights,
        "customer_type": c.customer_type,
        "market": c.market,
        "product_type": c.product_type,
        "key_phrases": c.key_phrases,
        "raw_summary": c.raw_summary,
        "original_content": c.original_content,
        "source_type": c.source_type,
        "image_path": c.image_path,
        "share_person": c.share_person,
        "share_date": c.share_date.isoformat() if c.share_date else None,
        "uploaded_by": c.uploaded_by,
        "status": c.status,
        "error_msg": c.error_msg,
        "like_count": c.like_count or 0,
        "view_count": c.view_count or 0,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "is_owner": current_user_id is not None and current_user_id == c.uploaded_by,
    }


# ──────────────────────────────────────────────────────
# 周会纪要(Minutes)
# ──────────────────────────────────────────────────────

@router.post("/minutes/upload")
def upload_minutes(
    data: MinutesUpload,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not _has_any_perm(user, ["insight:write", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:write")
    user_id = int(user.get("sub"))
    m = service.upload_minutes(db, user_id, data)
    return _ok({"id": m.id, "status": m.status, "error_msg": m.error_msg}, "上传成功")


@router.get("/minutes/{minutes_id}/status")
def get_minutes_status(
    minutes_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    return _ok(service.get_minutes_status(db, minutes_id))


@router.get("/minutes")
def list_minutes(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    return _ok(service.list_minutes(db, start_date=start_date, end_date=end_date, page=page, page_size=page_size))


@router.get("/minutes/{minutes_id}")
def get_minutes_detail(
    minutes_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    return _ok(service.get_minutes_detail(db, minutes_id))


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    data: TaskUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    user_id = int(user.get("sub"))
    t = service.update_task(db, task_id, user_id, data)
    return _ok({
        "id": t.id,
        "minutes_id": t.minutes_id,
        "status": t.status,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "completed_by": t.completed_by,
        "notes": t.notes,
    })


@router.get("/minutes/{minutes_id}/tasks/export")
def export_tasks(
    minutes_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    filename, csv_text = service.export_tasks_csv(db, minutes_id)
    # 加 BOM 让 Excel 直接识别 UTF-8
    body = "﻿" + csv_text
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────────────────────────────────────
# 工作台首页摘要
# ──────────────────────────────────────────────────────

@router.get("/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    user_name = user.get("username", "")
    return _ok(service.get_dashboard_summary(db, user_name=user_name))
