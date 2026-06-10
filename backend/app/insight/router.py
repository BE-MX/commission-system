"""方舟洞见 — API 路由"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import get_current_user
from app.insight import service
from app.insight.schemas import (
    CaseManualCreate,
    CasePublish,
    CaseUpdate,
    MinutesUpload,
    ReportImport,
    SourceCreate,
    SourceUpdate,
    SourceCreateV2,
    TaskUpdate,
    InsightItemCreate,
    InsightItemUpdate,
    IntelligenceReportGenerate,
    ScheduleRuleCreate,
    ScheduleRuleUpdate,
)

logger = logging.getLogger("insight")
from app.insight.dependencies import (
    _has_perm,
    _has_any_perm,
    _require_insight_view,
    _require_insight_admin,
    _require_opportunity_read,
    _require_opportunity_write,
    _require_opportunity_manage,
    _verify_import_api_key,
    _serialize_source,
)

router = APIRouter()

INTERNAL_REPORT_TYPES = {"shop_analysis", "competitor_analysis", "inquiry_analysis"}


def _ok(data, message: str = "ok"):
    return {"code": 200, "message": message, "data": data}


# ──────────────────────────────────────────────────────
# 报告(Reports)
# ──────────────────────────────────────────────────────

# ── 情报速览报告（固定路径放前面，避免被 /reports/{report_id} 吞掉）──
@router.get("/reports/intelligence")
def list_intelligence(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    from app.insight.intelligence_service import list_intelligence_reports
    result = list_intelligence_reports(db, status=status, page=page, page_size=page_size)
    return _ok(result)


@router.post("/reports/intelligence/generate")
def generate_intelligence(
    data: IntelligenceReportGenerate,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    """手动触发生成行业情报速览报告。"""
    from app.insight.intelligence_service import generate_intelligence_report
    try:
        user_id = int(user.get("sub")) if user.get("sub") else None
        report = generate_intelligence_report(db, data, user_id=user_id)
        return _ok({
            "id": report.id,
            "status": report.status,
            "title": report.title,
        }, "报告生成中")
    except Exception as e:
        logger.exception("生成情报速览失败")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)[:200]}")


@router.get("/reports/intelligence/{report_id}/html")
def get_intelligence_html(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    from app.insight.intelligence_service import get_intelligence_report_html
    try:
        html = get_intelligence_report_html(db, report_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.delete("/reports/intelligence/{report_id}")
def delete_intelligence(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.intelligence_service import delete_intelligence_report
    try:
        delete_intelligence_report(db, report_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _ok(None, "已删除")


@router.patch("/reports/intelligence/{report_id}/pin")
def pin_intelligence(
    report_id: int,
    is_pinned: bool = Query(True),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.intelligence_service import pin_report
    report = pin_report(db, report_id, is_pinned)
    return _ok({"id": report.id, "is_pinned": bool(report.is_pinned)}, "已更新")


# ── 通用报告 ─────────────────────────────────────────
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
    r = service.get_report(db, report_id)
    try:
        if r.report_type == "industry_daily":
            report = service.generate_industry_daily_report(db, report_date=r.report_date)
        elif r.report_type == "ai_tools":
            report = service.generate_ai_tools_report(db, report_date=r.report_date)
        else:
            raise HTTPException(status_code=400, detail=f"暂不支持重新生成 {r.report_type} 类型")
        return _ok({"id": report.id, "status": report.status}, "已重新生成")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Regenerate report failed: id=%s", report_id)
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)[:200]}")


@router.post("/reports/generate/{report_type}")
def trigger_report_generation(
    report_type: str,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    """手动触发报告生成（管理员用）。"""
    if report_type not in ("industry_daily", "ai_tools"):
        raise HTTPException(status_code=400, detail="report_type 仅支持 industry_daily 或 ai_tools")
    try:
        if report_type == "industry_daily":
            report = service.generate_industry_daily_report(db, report_date=date.today())
        else:
            report = service.generate_ai_tools_report(db, report_date=date.today())
        return _ok(
            {"id": report.id, "report_type": report.report_type, "status": report.status},
            "报告生成成功",
        )
    except Exception as e:
        logger.exception("手动生成报告失败: %s", report_type)
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)[:200]}")


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


@router.post("/sources/{source_id}/collect")
def trigger_source_collection(
    source_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    """对指定信源立即触发一次采集。"""
    from app.insight.collector_service import collect_source
    result = collect_source(db, source_id)
    return _ok(result)


# ──────────────────────────────────────────────────────
# 定时规则(Schedule Rules)
# ──────────────────────────────────────────────────────

@router.get("/schedule-rules")
def list_schedule_rules(
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.schedule_service import list_rules
    rows = list_rules(db, is_active=is_active)
    return _ok([{
        "id": r.id,
        "rule_name": r.rule_name,
        "is_active": bool(r.is_active),
        "cron_expression": r.cron_expression,
        "config_json": r.config_json,
        "notify_dingtalk": bool(r.notify_dingtalk),
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows])


@router.post("/schedule-rules")
def create_schedule_rule(
    data: ScheduleRuleCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.schedule_service import create_rule
    r = create_rule(db, data)
    return _ok({
        "id": r.id,
        "rule_name": r.rule_name,
        "is_active": bool(r.is_active),
        "cron_expression": r.cron_expression,
    }, "创建成功")


@router.put("/schedule-rules/{rule_id}")
def update_schedule_rule(
    rule_id: int,
    data: ScheduleRuleUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.schedule_service import update_rule
    r = update_rule(db, rule_id, data)
    return _ok({
        "id": r.id,
        "rule_name": r.rule_name,
        "is_active": bool(r.is_active),
    }, "更新成功")


@router.patch("/schedule-rules/{rule_id}/toggle")
def toggle_schedule_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.schedule_service import toggle_rule
    r = toggle_rule(db, rule_id)
    return _ok({"id": r.id, "is_active": bool(r.is_active)}, "已切换")


# ──────────────────────────────────────────────────────
# 情报条目(Items)
# ──────────────────────────────────────────────────────

@router.get("/items")
def list_items(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    source_ids: Optional[str] = Query(None, description="逗号分隔信源ID"),
    source_types: Optional[str] = Query(None, description="逗号分隔信源类型"),
    item_types: Optional[str] = Query(None, description="逗号分隔条目类型"),
    credibility_labels: Optional[str] = Query(None, description="逗号分隔可信度标签"),
    tags: Optional[str] = Query(None, description="逗号分隔标签"),
    is_featured: Optional[bool] = None,
    status: Optional[str] = Query(None, description="active/archived/flagged"),
    keyword: Optional[str] = None,
    sort_by: str = Query("collected_at"),
    sort_desc: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    from app.insight.item_service import list_items as _list_items
    result = _list_items(
        db,
        start_date=start_date,
        end_date=end_date,
        source_ids=[int(x) for x in source_ids.split(",") if x.strip()] if source_ids else None,
        source_types=[x.strip() for x in source_types.split(",") if x.strip()] if source_types else None,
        item_types=[x.strip() for x in item_types.split(",") if x.strip()] if item_types else None,
        credibility_labels=[x.strip() for x in credibility_labels.split(",") if x.strip()] if credibility_labels else None,
        tags=[x.strip() for x in tags.split(",") if x.strip()] if tags else None,
        is_featured=is_featured,
        status=status,
        keyword=keyword,
        sort_by=sort_by,
        sort_desc=sort_desc,
        page=page,
        page_size=page_size,
    )
    # SQLAlchemy ORM 对象不能直接 JSON 序列化，需要手动转 dict
    items = [_serialize_item(item) for item in result["items"]]
    return _ok({"total": result["total"], "items": items, "page": result["page"], "page_size": result["page_size"]})


@router.get("/items/{item_id}")
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_view),
):
    from app.insight.item_service import get_item as _get_item
    item = _get_item(db, item_id)
    return _ok(_serialize_item_detail(item))


@router.patch("/items/{item_id}/feature")
def toggle_item_feature(
    item_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.item_service import toggle_feature
    item = toggle_feature(db, item_id)
    return _ok(_serialize_item(item), "已更新")


@router.patch("/items/{item_id}/status")
def update_item_status(
    item_id: int,
    status: str = Query(..., description="active/archived/flagged"),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.item_service import update_status
    item = update_status(db, item_id, status)
    return _ok(_serialize_item(item), "已更新")


@router.post("/items/upload")
async def upload_md(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    """手工上传 MD 文件入库。"""
    from app.insight.item_service import upload_manual_md
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")
    content = (await file.read()).decode("utf-8", errors="replace")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    item = upload_manual_md(db, title=title or file.filename, content_md=content, tags=tag_list)
    return _ok(_serialize_item(item), "上传成功")


@router.post("/items/batch/feature")
def batch_feature(
    item_ids: list[int],
    is_featured: bool = True,
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.item_service import batch_toggle_feature
    count = batch_toggle_feature(db, item_ids, is_featured)
    return _ok({"count": count}, "批量更新成功")


@router.post("/items/batch/status")
def batch_status(
    item_ids: list[int],
    status: str = Query(...),
    db: Session = Depends(get_db),
    user: dict = Depends(_require_insight_admin),
):
    from app.insight.item_service import batch_update_status
    count = batch_update_status(db, item_ids, status)
    return _ok({"count": count}, "批量更新成功")


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


@router.put("/cases/{case_id}")
def update_case(
    case_id: int,
    data: CaseUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not _has_any_perm(user, ["insight:write", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:write")
    user_id = int(user.get("sub"))
    is_admin = _has_perm(user, "insight:admin")
    case = service.update_case(db, case_id, user_id, is_admin, data)
    return _ok(_serialize_case(case, user_id), "已更新")


@router.get("/cases")
def list_cases(
    share_person: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    product_type: Optional[str] = None,
    market: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = Query("date", pattern="^(date|likes)$"),
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
    return _ok(None, "已删除")


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
        # SKILL-based 扩展字段
        "customer_country": c.customer_country,
        "communication_channel": c.communication_channel,
        "communication_period": c.communication_period,
        "total_rounds": c.total_rounds,
        "final_result": c.final_result,
        "background_check_status": c.background_check_status,
        "rounds_analysis": c.rounds_analysis,
        "dimension_scores": c.dimension_scores,
        "golden_phrases": c.golden_phrases,
        "red_flags": c.red_flags,
        "core_strengths": c.core_strengths,
        "result_analysis": c.result_analysis,
        "improvements": c.improvements,
        "next_actions": c.next_actions,
        "ai_draft": c.ai_draft,
        "user_corrections": c.user_corrections,
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


# ── 序列化辅助 ──────────────────────────────────────────

def _serialize_item(item) -> dict:
    return {
        "id": item.id,
        "source_id": item.source_id,
        "source_type": item.source_type,
        "collected_at": item.collected_at.isoformat() if item.collected_at else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "original_url": item.original_url,
        "title": item.title,
        "content_mode": item.content_mode,
        "content_md": item.content_md,
        "credibility_score": item.credibility_score,
        "credibility_label": item.credibility_label,
        "tags": item.tags or [],
        "item_type": item.item_type,
        "related_competitor": item.related_competitor,
        "is_featured": bool(item.is_featured),
        "status": item.status,
        "like_count": item.like_count,
        "comment_count": item.comment_count,
        "media_type": item.media_type,
        "ai_signal": item.ai_signal,
        "priority": item.priority,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _serialize_item_detail(item) -> dict:
    base = _serialize_item(item)
    base.update({
        "credibility_note": item.credibility_note,
        "ai_meaning": item.ai_meaning,
        "ai_action_hint": item.ai_action_hint,
    })
    return base


# ──────────────────────────────────────────────────────
# ── 客户机会台 ───────────────────────────────────────
# ──────────────────────────────────────────────────────

@router.post("/customer-opportunities/import/accio", summary="ACCIO WORK 导入询盘")
def import_accio(
    payload: dict,
    db: Session = Depends(get_db),
    _authed: bool = Depends(_verify_import_api_key),
):
    from app.insight.customer_opportunity_service import import_accio_inquiries
    result = import_accio_inquiries(db, payload)
    return _ok(result, message="导入完成")


@router.get("/customer-opportunities/my", summary="我的客户机会")
def list_my_opportunities(
    status: str = Query(None),
    priority_level: str = Query(None),
    source: str = Query(None),
    keyword: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_read),
):
    from app.insight.customer_opportunity_service import list_my_opportunities as _list
    user_id = _user["sub"]
    result = _list(db, user_id, status, priority_level, source, keyword, date_from, date_to, page, page_size)
    return _ok({
        "items": [_serialize_opportunity(o) for o in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.get("/customer-opportunities/stats", summary="我的机会统计")
def get_my_stats(
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_read),
):
    from app.insight.customer_opportunity_service import get_opportunity_stats
    user_id = _user["sub"]
    return _ok(get_opportunity_stats(db, user_id))


@router.get("/customer-opportunities/{opp_id}", summary="机会详情")
def get_opportunity_detail(
    opp_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_read),
):
    from app.insight.customer_opportunity_service import get_opportunity
    opp = get_opportunity(db, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="机会不存在")
    # 非 manage 权限只能看自己的
    if not _has_perm(_user, "customer_opportunity:manage") and opp.owner_user_id != _user["sub"]:
        raise HTTPException(status_code=403, detail="无权查看该机会")
    return _ok(_serialize_opportunity_detail(opp))


@router.put("/customer-opportunities/{opp_id}/status", summary="更新机会状态")
def update_opp_status(
    opp_id: int,
    status: str = Query(..., description="新状态"),
    note: str = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_write),
):
    from app.insight.customer_opportunity_service import update_opportunity_status
    try:
        opp = update_opportunity_status(db, opp_id, status, note, _user["sub"])
        return _ok({"id": opp.id, "status": opp.status}, message="状态已更新")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/customer-opportunities/{opp_id}/feedback", summary="添加反馈")
def add_opp_feedback(
    opp_id: int,
    feedback: str = Query(..., description="useful/not_useful"),
    note: str = Query(None),
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_write),
):
    from app.insight.customer_opportunity_service import add_opportunity_feedback
    try:
        add_opportunity_feedback(db, opp_id, feedback, note, _user["sub"])
        return _ok(None, message="反馈已记录")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/customer-opportunities/admin/all", summary="管理员: 全部机会")
def admin_list_all(
    status: str = Query(None),
    priority_level: str = Query(None),
    owner_user_id: int = Query(None),
    resolve_status: str = Query(None),
    keyword: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_manage),
):
    from app.insight.customer_opportunity_service import list_all_opportunities as _list
    result = _list(db, status, priority_level, owner_user_id, resolve_status, keyword, page, page_size)
    return _ok({
        "items": [_serialize_opportunity(o) for o in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.get("/customer-opportunities/admin/unassigned", summary="管理员: 未分配机会")
def admin_list_unassigned(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_manage),
):
    from app.insight.customer_opportunity_service import list_unassigned_opportunities as _list
    result = _list(db, page, page_size)
    return _ok({
        "items": [_serialize_opportunity(o) for o in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.put("/customer-opportunities/{opp_id}/assign", summary="管理员: 分配机会")
def admin_assign(
    opp_id: int,
    user_id: int = Query(..., description="方舟用户ID"),
    db: Session = Depends(get_db),
    _user: dict = Depends(_require_opportunity_manage),
):
    from app.insight.customer_opportunity_service import assign_opportunity
    try:
        opp = assign_opportunity(db, opp_id, user_id, _user["sub"])
        return _ok({"id": opp.id, "owner_user_id": opp.owner_user_id}, message="已分配")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 机会序列化 ──────────────────────────────────────────

def _serialize_opportunity(o) -> dict:
    return {
        "id": o.id,
        "opportunity_type": o.opportunity_type,
        "source": o.source,
        "source_key": o.source_key,
        "owner_user_id": o.owner_user_id,
        "owner_resolve_status": o.owner_resolve_status,
        "customer_name": o.customer_name,
        "customer_region": o.customer_region,
        "priority_level": o.priority_level,
        "confidence_score": o.confidence_score,
        "urgency": o.urgency,
        "title": o.title,
        "summary": o.summary,
        "status": o.status,
        "feedback": o.feedback,
        "due_at": o.due_at.isoformat() if o.due_at else None,
        "latest_message_at": o.latest_message_at.isoformat() if o.latest_message_at else None,
        "handled_at": o.handled_at.isoformat() if o.handled_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def _serialize_opportunity_detail(o) -> dict:
    base = _serialize_opportunity(o)
    base.update({
        "source_ref_type": o.source_ref_type,
        "source_ref_id": o.source_ref_id,
        "source_owner_external_json": o.source_owner_external_json,
        "customer_external_id": o.customer_external_id,
        "key_signals_json": o.key_signals_json,
        "background_check_json": o.background_check_json,
        "recommended_strategy": o.recommended_strategy,
        "opening_message_en": o.opening_message_en,
        "follow_up_message_en": o.follow_up_message_en,
        "evidence_json": o.evidence_json,
    })
    return base
