"""客户售后管理 HTTP API。业务逻辑位于 service 层。"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.aftersales import query_service, service
from app.aftersales.file_service import (
    FileValidationError,
    resolve_private_path,
    store_bytes,
    validate_upload,
)
from app.aftersales.ai_service import AiAnalysisError, run_analysis
from app.aftersales.models import (
    AfterSalesAiRun,
    AfterSalesCase,
    AfterSalesEvent,
    AfterSalesEvidence,
    AfterSalesNotificationLog,
    AfterSalesReview,
    AfterSalesSopVersion,
)
from app.aftersales.notification_service import deliver_notification
from app.aftersales.schemas import (
    CaseCreate,
    CloseRequest,
    DecisionRequest,
    EvidenceWaiverRequest,
    EvidenceWaiverReviewRequest,
    ExecutionRequest,
    ISSUE_TYPES,
    ReviewRequest,
    ReasonRequest,
    TransferApprovalRequest,
    VersionedActionRequest,
)
from app.aftersales.sop_service import activate_sop_version, create_sop_version
from app.auth.dependencies import require_any_permission, require_permission
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.database import get_db
from app.core.database import SessionLocal
from app.core.response import ok, page_result


router = APIRouter()


ACTIONS = [
    {"code": "explanation", "label": "原因解释/预期管理", "has_compensation": False},
    {"code": "care_guidance", "label": "护理建议", "has_compensation": False},
    {"code": "return_inspection", "label": "返厂检测", "has_compensation": None},
    {"code": "paid_rework", "label": "客户付费二次处理", "has_compensation": False},
    {"code": "free_rework", "label": "公司承担二次处理", "has_compensation": True},
    {"code": "replacement", "label": "免费换货/重做", "has_compensation": True},
    {"code": "resend", "label": "免费补发", "has_compensation": True},
    {"code": "cash_refund", "label": "现金退款", "has_compensation": True},
    {"code": "discount", "label": "折扣支持", "has_compensation": True},
    {"code": "order_credit", "label": "下单抵扣", "has_compensation": True},
    {"code": "freight_subsidy", "label": "运费补贴", "has_compensation": True},
    {"code": "custom", "label": "其他", "has_compensation": None},
]


def _storage_root() -> Path:
    return Path(get_settings().AFTERSALES_STORAGE_ROOT)


def _ark_user(db: Session, payload: dict) -> ArkUser:
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="登录用户信息无效") from exc
    user = (
        db.query(ArkUser)
        .filter(ArkUser.id == user_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="登录用户不存在或已停用")
    return user


def _can_view(case: AfterSalesCase, user: ArkUser, payload: dict) -> bool:
    if "aftersales:read_all" in payload.get("permissions", []) or "super_admin" in payload.get("roles", []):
        return True
    return user.id in {
        case.creator_user_id,
        case.current_owner_user_id,
        case.supervisor_user_id_snapshot,
        case.director_user_id_snapshot,
    }


def _get_visible_case(db: Session, case_id: int, user: ArkUser, payload: dict) -> AfterSalesCase:
    case = (
        db.query(AfterSalesCase)
        .filter(AfterSalesCase.id == case_id, AfterSalesCase.deleted_at.is_(None))
        .first()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="售后单不存在")
    if not _can_view(case, user, payload):
        raise HTTPException(status_code=403, detail="无权查看该售后单")
    return case


def _decimal(value):
    return str(value) if isinstance(value, Decimal) else value


def _case_data(case: AfterSalesCase) -> dict:
    fields = [
        "id", "case_no", "creator_user_id", "creator_name_snapshot", "customer_id",
        "customer_name_snapshot", "customer_grade", "order_id", "order_no_snapshot",
        "purchase_date", "feedback_date", "feedback_channel", "product_id",
        "product_name_snapshot", "is_custom_product", "batch_no", "color_value",
        "length_value", "weight_value", "weight_unit", "quantity", "primary_issue_type",
        "secondary_issue_types_json", "problem_description", "occurred_stage",
        "care_storage_note", "affects_end_customer", "affected_goods_value",
        "affected_goods_currency", "sales_evidence_confirmed", "sales_evidence_note",
        "evidence_score", "evidence_is_sufficient", "evidence_missing_items_json",
        "evidence_waiver_approved", "evidence_waiver_reason",
        "evidence_waiver_decision_note", "evidence_waived_by_user_id", "evidence_waived_at",
        "responsibility_class", "responsibility_reason", "responsibility_override_reason",
        "selected_actions_json", "has_compensation", "estimated_compensation_usd",
        "requires_return", "customer_reply_draft", "execution_result", "customer_feedback",
        "sop_version_id", "current_status", "current_owner_user_id",
        "supervisor_user_id_snapshot", "director_user_id_snapshot", "workflow_round",
        "version", "approved_at", "closed_at", "created_at", "updated_at",
    ]
    return {name: _decimal(getattr(case, name)) for name in fields}


def _evidence_data(item: AfterSalesEvidence) -> dict:
    return {
        "id": item.id,
        "case_id": item.case_id,
        "evidence_type": item.evidence_type,
        "original_filename": item.original_filename,
        "mime_type": item.mime_type,
        "file_size": item.file_size,
        "summary": item.summary,
        "download_url": f"/api/aftersales/evidence/{item.id}/download",
        "created_at": item.created_at,
    }


def _sop_data(version: AfterSalesSopVersion, db: Session | None = None) -> dict:
    data = {
        "id": version.id,
        "version_no": version.version_no,
        "original_filename": version.original_filename,
        "change_summary": version.change_summary,
        "effective_date": version.effective_date,
        "parse_status": version.parse_status,
        "issue_mapping": version.issue_mapping_json or {},
        "structured_content": version.structured_content_json or {},
        "clause_count": version.clause_count,
        "is_active": version.is_active,
        "activated_at": version.activated_at,
        "created_at": version.created_at,
    }
    if db is not None:
        uploader = db.get(ArkUser, version.uploaded_by_user_id)
        data["uploaded_by_name"] = uploader.real_name if uploader else None
        data["reference_count"] = (
            db.query(func.count(AfterSalesCase.id))
            .filter(AfterSalesCase.sop_version_id == version.id)
            .scalar()
            or 0
        )
    return data


def _to_http_error(exc: Exception):
    if isinstance(exc, service.VersionConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (service.WorkflowOperationError, FileValidationError, ValueError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _run_analysis_task(case_id: int, user_id: int) -> None:
    with SessionLocal() as db:
        try:
            run_analysis(db, case_id, user_id)
            db.commit()
        except Exception as exc:
            db.commit()
            print(f"[AFTERSALES] AI analysis failed case_id={case_id}: {exc}", flush=True)


async def _deliver_notification_task(notification_ids: list[int]) -> None:
    for notification_id in notification_ids:
        with SessionLocal() as db:
            await deliver_notification(db, notification_id)


def _pending_notification_ids(db: Session, case_id: int) -> list[int]:
    return [
        row[0]
        for row in db.query(AfterSalesNotificationLog.id)
        .filter(
            AfterSalesNotificationLog.case_id == case_id,
            AfterSalesNotificationLog.status == "pending",
        )
        .all()
    ]


@router.get("/options", summary="售后问题、措施和证据规则")
def options(_payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin"))):
    return ok(
        {
            "issue_types": [
                {
                    "code": issue,
                    "label": issue,
                    "secondary": [
                        "贴发/天才发帘抹胶厚薄不匀",
                        "包装细节出错",
                        "其他做工问题",
                    ] if issue == "产品做工" else [],
                }
                for issue in ISSUE_TYPES
            ],
            "actions": ACTIONS,
            "customer_grades": ["A", "B", "C", "D", "E"],
            "responsibility_classes": ["A", "B", "C", "D"],
        }
    )


@router.get("/cases", summary="售后单列表")
def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    status: str | None = None,
    issue_type: str | None = None,
    customer_grade: str | None = None,
    responsibility_class: str | None = None,
    has_compensation: bool | None = None,
    creator_user_id: int | None = None,
    current_owner_user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    assigned_to_me: bool = False,
    scope: str = "mine",
    db: Session = Depends(get_db),
    payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    user = _ark_user(db, payload)
    query = db.query(AfterSalesCase).filter(AfterSalesCase.deleted_at.is_(None))
    can_read_all = "aftersales:read_all" in payload.get("permissions", []) or "super_admin" in payload.get("roles", [])
    if assigned_to_me:
        query = query.filter(AfterSalesCase.current_owner_user_id == user.id)
    elif scope != "all" or not can_read_all:
        query = query.filter(
            or_(
                AfterSalesCase.creator_user_id == user.id,
                AfterSalesCase.current_owner_user_id == user.id,
                AfterSalesCase.supervisor_user_id_snapshot == user.id,
                AfterSalesCase.director_user_id_snapshot == user.id,
            )
        )
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                AfterSalesCase.case_no.like(pattern),
                AfterSalesCase.customer_name_snapshot.like(pattern),
                AfterSalesCase.order_no_snapshot.like(pattern),
            )
        )
    if status:
        query = query.filter(AfterSalesCase.current_status == status)
    if issue_type:
        query = query.filter(AfterSalesCase.primary_issue_type == issue_type)
    if customer_grade:
        query = query.filter(AfterSalesCase.customer_grade == customer_grade)
    if responsibility_class:
        query = query.filter(AfterSalesCase.responsibility_class == responsibility_class)
    if has_compensation is not None:
        query = query.filter(AfterSalesCase.has_compensation.is_(has_compensation))
    if creator_user_id:
        query = query.filter(AfterSalesCase.creator_user_id == creator_user_id)
    if current_owner_user_id:
        query = query.filter(AfterSalesCase.current_owner_user_id == current_owner_user_id)
    if date_from:
        query = query.filter(AfterSalesCase.feedback_date >= date_from)
    if date_to:
        query = query.filter(AfterSalesCase.feedback_date <= date_to)
    total = query.count()
    items = (
        query.order_by(AfterSalesCase.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    owner_ids = {item.current_owner_user_id for item in items if item.current_owner_user_id}
    owner_names = {
        owner.id: owner.real_name
        for owner in db.query(ArkUser).filter(ArkUser.id.in_(owner_ids)).all()
    } if owner_ids else {}
    now = datetime.utcnow()
    rows = []
    for item in items:
        row = _case_data(item)
        row["current_owner_name"] = owner_names.get(item.current_owner_user_id)
        row["waiting_hours"] = round((now - item.updated_at).total_seconds() / 3600, 1) if item.updated_at else 0
        rows.append(row)
    return ok(page_result(rows, total, page, page_size))


@router.get("/customers/search", summary="搜索售后客户")
def customer_search(
    keyword: str = "",
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    return ok({"items": query_service.search_customers(db, keyword, limit)})


@router.get("/orders/search", summary="按客户搜索订单")
def order_search(
    customer_id: str,
    keyword: str = "",
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    try:
        return ok({"items": query_service.search_orders(db, customer_id, keyword, limit)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/products/search", summary="搜索售后产品")
def product_search(
    keyword: str = "",
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    return ok({"items": query_service.search_products(db, keyword, limit)})


@router.get("/reviewers/search", summary="管理员搜索可转交审批人")
def reviewer_search(
    keyword: str = "",
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _payload=Depends(require_permission("aftersales:admin")),
):
    query = db.query(ArkUser).filter(
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
        ArkUser.dingtalk_id.isnot(None),
    )
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(ArkUser.real_name.like(pattern), ArkUser.username.like(pattern)))
    users = query.order_by(ArkUser.real_name, ArkUser.id).limit(limit).all()
    return ok(
        {
            "items": [
                {"user_id": user.id, "real_name": user.real_name, "username": user.username}
                for user in users
            ]
        }
    )


@router.get("/people/search", summary="搜索售后业务员与审批人")
def people_search(
    keyword: str = "",
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    query = db.query(ArkUser).filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(ArkUser.real_name.like(pattern), ArkUser.username.like(pattern)))
    users = query.order_by(ArkUser.real_name, ArkUser.id).limit(limit).all()
    return ok({"items": [{"user_id": user.id, "real_name": user.real_name} for user in users]})


@router.post("/cases", summary="创建售后草稿")
def create_case(
    body: CaseCreate,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.create_case(db, body, user)
        db.commit()
        db.refresh(case)
        return ok(_case_data(case), message="售后草稿已创建")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.put("/cases/{case_id}", summary="更新可编辑售后单")
def update_case(
    case_id: int,
    body: CaseCreate,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.update_case(db, case_id, body, user)
        db.commit()
        db.refresh(case)
        return ok(_case_data(case), message="售后单已保存")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.delete("/cases/{case_id}", summary="删除本人草稿")
def delete_case(
    case_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        service.delete_draft(db, case_id, user)
        db.commit()
        return ok(message="售后草稿已删除")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.get("/cases/{case_id}", summary="售后单详情")
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    user = _ark_user(db, payload)
    case = _get_visible_case(db, case_id, user, payload)
    data = _case_data(case)
    evidence = (
        db.query(AfterSalesEvidence)
        .filter(AfterSalesEvidence.case_id == case.id, AfterSalesEvidence.deleted_at.is_(None))
        .order_by(AfterSalesEvidence.created_at)
        .all()
    )
    data["evidence"] = [_evidence_data(item) for item in evidence]
    return ok(data)


@router.post("/cases/{case_id}/evidence", summary="上传售后证据")
async def upload_evidence(
    case_id: int,
    evidence_type: str = Form(...),
    summary: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    case = _get_visible_case(db, case_id, user, payload)
    if case.creator_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有创建人可以上传证据")
    if case.current_status not in service.EDITABLE_STATUSES:
        raise HTTPException(status_code=400, detail="售后单已提交，证据已锁定")
    content = await file.read()
    try:
        validate_upload(file.filename or "", file.content_type or "", len(content), purpose="evidence")
        current_total = (
            db.query(AfterSalesEvidence.file_size)
            .filter(AfterSalesEvidence.case_id == case.id, AfterSalesEvidence.deleted_at.is_(None))
            .all()
        )
        if sum(row[0] for row in current_total) + len(content) > 1024 * 1024 * 1024:
            raise FileValidationError("单张售后单附件总量不能超过 1GB")
        relative_path = store_bytes(_storage_root(), "evidence", file.filename or "file", content)
        item = AfterSalesEvidence(
            case_id=case.id,
            evidence_type=evidence_type,
            original_filename=file.filename or "file",
            storage_path=relative_path,
            mime_type=file.content_type or "application/octet-stream",
            file_size=len(content),
            summary=summary,
            uploaded_by_user_id=user.id,
        )
        db.add(item)
        db.flush()
        service.invalidate_evidence_waiver(case)
        service.refresh_evidence(db, case)
        case.version += 1
        db.commit()
        db.refresh(item)
        return ok(_evidence_data(item), message="证据已上传")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.get("/evidence/{evidence_id}/download", summary="鉴权下载售后证据")
def download_evidence(
    evidence_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    user = _ark_user(db, payload)
    item = (
        db.query(AfterSalesEvidence)
        .filter(AfterSalesEvidence.id == evidence_id, AfterSalesEvidence.deleted_at.is_(None))
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    _get_visible_case(db, item.case_id, user, payload)
    path = resolve_private_path(_storage_root(), item.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="证据文件不存在")
    return FileResponse(path, media_type=item.mime_type, filename=item.original_filename)


@router.delete("/cases/{case_id}/evidence/{evidence_id}", summary="删除可编辑证据")
def delete_evidence(
    case_id: int,
    evidence_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    case = _get_visible_case(db, case_id, user, payload)
    if case.creator_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有创建人可以删除证据")
    if case.current_status not in service.EDITABLE_STATUSES:
        raise HTTPException(status_code=400, detail="售后单已提交，证据已锁定")
    item = (
        db.query(AfterSalesEvidence)
        .filter(
            AfterSalesEvidence.id == evidence_id,
            AfterSalesEvidence.case_id == case.id,
            AfterSalesEvidence.deleted_at.is_(None),
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    item.deleted_at = datetime.utcnow()
    service.invalidate_evidence_waiver(case)
    service.refresh_evidence(db, case)
    case.version += 1
    db.commit()
    return ok(message="证据已删除")


@router.post("/cases/{case_id}/analyze", summary="异步发起 AI 售后建议")
def analyze_case(
    case_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    case = _get_visible_case(db, case_id, user, payload)
    if case.creator_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有创建人可以发起 AI 分析")
    if case.current_status not in service.EDITABLE_STATUSES:
        raise HTTPException(status_code=400, detail="当前状态不能发起 AI 分析")
    if not db.query(AfterSalesSopVersion.id).filter(AfterSalesSopVersion.is_active.is_(True)).first():
        raise HTTPException(status_code=400, detail="当前没有生效的售后 SOP")
    case.current_status = "ai_analyzing"
    case.version += 1
    db.commit()
    background_tasks.add_task(_run_analysis_task, case.id, user.id)
    return ok({"case_id": case.id, "status": "ai_analyzing"}, message="AI 分析已开始")


@router.post("/cases/{case_id}/decision", summary="保存业务员处理决定")
def save_case_decision(
    case_id: int,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.save_decision(
            db,
            case_id,
            user,
            responsibility_class=body.responsibility_class,
            responsibility_reason=body.responsibility_reason,
            responsibility_override_reason=body.responsibility_override_reason,
            actions=body.actions,
            customer_reply_draft=body.customer_reply_draft,
            requires_return=body.requires_return,
        )
        db.commit()
        db.refresh(case)
        return ok(_case_data(case), message="处理决定已保存")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/evidence-waiver/request", summary="申请主管证据豁免")
def request_case_evidence_waiver(
    case_id: int,
    body: EvidenceWaiverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.request_evidence_waiver(
            db,
            case_id,
            user,
            reason=body.reason,
            version=body.version,
            idempotency_key=body.idempotency_key,
        )
        db.commit()
        db.refresh(case)
        notification_ids = _pending_notification_ids(db, case.id)
        if notification_ids:
            background_tasks.add_task(_deliver_notification_task, notification_ids)
        return ok(_case_data(case), message="证据豁免申请已提交直属主管")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/evidence-waiver/review", summary="直属主管确认证据豁免")
def review_case_evidence_waiver(
    case_id: int,
    body: EvidenceWaiverReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:review")),
):
    user = _ark_user(db, payload)
    try:
        case = service.review_evidence_waiver(
            db,
            case_id,
            user,
            decision=body.decision,
            comment=body.comment,
            version=body.version,
            idempotency_key=body.idempotency_key,
        )
        db.commit()
        db.refresh(case)
        notification_ids = _pending_notification_ids(db, case.id)
        if notification_ids:
            background_tasks.add_task(_deliver_notification_task, notification_ids)
        return ok(_case_data(case), message="证据豁免审核结果已保存")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/submit", summary="提交直属主管审核")
def submit_case(
    case_id: int,
    body: VersionedActionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.submit_case(
            db,
            case_id,
            user,
            version=body.version,
            idempotency_key=body.idempotency_key,
        )
        db.commit()
        db.refresh(case)
        notification_ids = _pending_notification_ids(db, case.id)
        if notification_ids:
            background_tasks.add_task(_deliver_notification_task, notification_ids)
        return ok(_case_data(case), message="已提交直属主管审核")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/review", summary="当前审批人审核")
def review_case(
    case_id: int,
    body: ReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:review")),
):
    user = _ark_user(db, payload)
    try:
        case = service.review_case(
            db,
            case_id,
            user,
            decision=body.decision,
            comment=body.comment,
            version=body.version,
            idempotency_key=body.idempotency_key,
            allow_proxy="super_admin" in payload.get("roles", []),
            proxy_reason=body.proxy_reason,
        )
        db.commit()
        db.refresh(case)
        notification_ids = _pending_notification_ids(db, case.id)
        if notification_ids:
            background_tasks.add_task(_deliver_notification_task, notification_ids)
        return ok(_case_data(case), message="审核结果已保存")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/transfer", summary="管理员转交当前审批")
def transfer_case_approval(
    case_id: int,
    body: TransferApprovalRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:admin")),
):
    user = _ark_user(db, payload)
    new_reviewer = db.get(ArkUser, body.new_reviewer_user_id)
    if new_reviewer is None:
        raise HTTPException(status_code=404, detail="新审批人不存在")
    try:
        case = service.transfer_approval(
            db,
            case_id,
            user,
            new_reviewer,
            reason=body.reason,
            version=body.version,
            idempotency_key=body.idempotency_key,
        )
        db.commit()
        db.refresh(case)
        notification_ids = _pending_notification_ids(db, case.id)
        if notification_ids:
            background_tasks.add_task(_deliver_notification_task, notification_ids)
        return ok(_case_data(case), message="当前审批已转交")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/withdraw", summary="撤回主管未审核单据")
def withdraw_case(
    case_id: int,
    body: VersionedActionRequest,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.withdraw_case(db, case_id, user, version=body.version)
        db.commit()
        db.refresh(case)
        return ok(_case_data(case), message="售后单已撤回")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/execute", summary="登记售后执行结果")
def execute_case(
    case_id: int,
    body: ExecutionRequest,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.execute_case(
            db, case_id, user, body.execution_result, body.customer_feedback
        )
        db.commit()
        db.refresh(case)
        return ok(_case_data(case), message="执行结果已保存")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/close", summary="关闭售后单")
def close_case(
    case_id: int,
    body: CloseRequest,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:write")),
):
    user = _ark_user(db, payload)
    try:
        case = service.close_case(db, case_id, user, body.customer_feedback)
        db.commit()
        db.refresh(case)
        return ok(_case_data(case), message="售后单已关闭")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/cases/{case_id}/reopen", summary="管理员重新打开售后单")
def reopen_case(
    case_id: int,
    body: ReasonRequest,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:admin")),
):
    user = _ark_user(db, payload)
    try:
        case = service.reopen_case(db, case_id, user, body.reason)
        db.commit()
        db.refresh(case)
        return ok(_case_data(case), message="售后单已重新打开")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.get("/cases/{case_id}/timeline", summary="售后审计时间线")
def case_timeline(
    case_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_any_permission("aftersales:read", "aftersales:write", "aftersales:review", "aftersales:admin")),
):
    user = _ark_user(db, payload)
    case = _get_visible_case(db, case_id, user, payload)
    events = (
        db.query(AfterSalesEvent)
        .filter(AfterSalesEvent.case_id == case.id)
        .order_by(AfterSalesEvent.created_at, AfterSalesEvent.id)
        .all()
    )
    reviews = (
        db.query(AfterSalesReview)
        .filter(AfterSalesReview.case_id == case.id)
        .order_by(AfterSalesReview.created_at, AfterSalesReview.id)
        .all()
    )
    ai_runs = (
        db.query(AfterSalesAiRun)
        .filter(AfterSalesAiRun.case_id == case.id)
        .order_by(AfterSalesAiRun.run_no)
        .all()
    )
    notifications = (
        db.query(AfterSalesNotificationLog)
        .filter(AfterSalesNotificationLog.case_id == case.id)
        .order_by(AfterSalesNotificationLog.created_at, AfterSalesNotificationLog.id)
        .all()
    )
    return ok(
        {
            "events": [
                {
                    "id": item.id,
                    "event_type": item.event_type,
                    "actor_name": item.actor_name_snapshot,
                    "workflow_round": item.workflow_round,
                    "detail": item.detail_json,
                    "created_at": item.created_at,
                }
                for item in events
            ],
            "reviews": [
                {
                    "id": item.id,
                    "reviewer_role": item.reviewer_role,
                    "reviewer_name": item.reviewer_name_snapshot,
                    "decision": item.decision,
                    "comment": item.remark,
                    "workflow_round": item.workflow_round,
                    "created_at": item.created_at,
                }
                for item in reviews
            ],
            "ai_runs": [
                {
                    "id": item.id,
                    "run_no": item.run_no,
                    "status": item.status,
                    "output": item.output_json,
                    "error_summary": item.error_summary,
                    "sop_version_id": item.sop_version_id,
                    "created_at": item.created_at,
                }
                for item in ai_runs
            ],
            "notifications": [
                {
                    "id": item.id,
                    "template_code": item.template_code,
                    "status": item.status,
                    "attempt_count": item.attempt_count,
                    "last_error_summary": item.last_error_summary,
                    "sent_at": item.sent_at,
                    "created_at": item.created_at,
                }
                for item in notifications
            ],
        }
    )


@router.get("/analytics/summary", summary="售后基础分析")
def analytics_summary(
    db: Session = Depends(get_db),
    # 2026-07-12 售后分析页独立码（062 迁移已给 aftersales:read 持有者补授）
    payload=Depends(require_any_permission("aftersales_analytics:read", "aftersales:admin")),
):
    user = _ark_user(db, payload)
    base = db.query(AfterSalesCase).filter(AfterSalesCase.deleted_at.is_(None))
    can_read_all = "aftersales:read_all" in payload.get("permissions", []) or "super_admin" in payload.get("roles", [])
    if not can_read_all:
        base = base.filter(
            or_(
                AfterSalesCase.creator_user_id == user.id,
                AfterSalesCase.current_owner_user_id == user.id,
                AfterSalesCase.supervisor_user_id_snapshot == user.id,
                AfterSalesCase.director_user_id_snapshot == user.id,
            )
        )
    total = base.count()
    compensation_total = base.with_entities(
        func.coalesce(func.sum(AfterSalesCase.estimated_compensation_usd), 0)
    ).scalar()
    issue_rows = (
        base.with_entities(AfterSalesCase.primary_issue_type, func.count(AfterSalesCase.id))
        .group_by(AfterSalesCase.primary_issue_type)
        .all()
    )
    status_rows = (
        base.with_entities(AfterSalesCase.current_status, func.count(AfterSalesCase.id))
        .group_by(AfterSalesCase.current_status)
        .all()
    )
    responsibility_rows = (
        base.with_entities(AfterSalesCase.responsibility_class, func.count(AfterSalesCase.id))
        .filter(AfterSalesCase.responsibility_class.isnot(None))
        .group_by(AfterSalesCase.responsibility_class)
        .all()
    )
    grade_rows = (
        base.with_entities(AfterSalesCase.customer_grade, func.count(AfterSalesCase.id))
        .group_by(AfterSalesCase.customer_grade)
        .all()
    )
    product_rows = (
        base.with_entities(AfterSalesCase.product_name_snapshot, func.count(AfterSalesCase.id))
        .group_by(AfterSalesCase.product_name_snapshot)
        .order_by(func.count(AfterSalesCase.id).desc())
        .limit(20)
        .all()
    )
    batch_name = func.coalesce(AfterSalesCase.batch_no, "未知")
    batch_rows = (
        base.with_entities(batch_name, func.count(AfterSalesCase.id))
        .group_by(batch_name)
        .order_by(func.count(AfterSalesCase.id).desc())
        .limit(20)
        .all()
    )
    compensation_count = base.filter(AfterSalesCase.has_compensation.is_(True)).count()
    trend_date = func.date(AfterSalesCase.created_at)
    trend_rows = (
        base.with_entities(
            trend_date,
            func.count(AfterSalesCase.id),
            func.coalesce(func.sum(AfterSalesCase.estimated_compensation_usd), 0),
        )
        .group_by(trend_date)
        .order_by(trend_date)
        .all()
    )
    closed_cases = base.filter(AfterSalesCase.closed_at.isnot(None)).all()
    approved_cases = base.filter(AfterSalesCase.approved_at.isnot(None)).all()

    def _average_hours(items, end_field: str) -> float | None:
        values = [
            (getattr(item, end_field) - item.created_at).total_seconds() / 3600
            for item in items
            if item.created_at and getattr(item, end_field)
        ]
        return round(sum(values) / len(values), 1) if values else None

    return ok(
        {
            "total": total,
            "compensation_total_usd": str(compensation_total),
            "compensation_case_count": compensation_count,
            "compensation_rate": round(compensation_count / total, 4) if total else 0,
            "average_approval_hours": _average_hours(approved_cases, "approved_at"),
            "average_resolution_hours": _average_hours(closed_cases, "closed_at"),
            "by_issue": [{"name": name, "count": count} for name, count in issue_rows],
            "by_status": [{"name": name, "count": count} for name, count in status_rows],
            "by_responsibility": [{"name": name, "count": count} for name, count in responsibility_rows],
            "by_customer_grade": [{"name": name, "count": count} for name, count in grade_rows],
            "by_product": [{"name": name, "count": count} for name, count in product_rows],
            "by_batch": [{"name": name, "count": count} for name, count in batch_rows],
            "trend": [
                {"date": str(day), "count": count, "compensation_usd": str(amount)}
                for day, count, amount in trend_rows
            ],
        }
    )


@router.post("/notifications/{notification_id}/retry", summary="管理员重试售后通知")
async def retry_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    _payload=Depends(require_permission("aftersales:admin")),
):
    try:
        item = await deliver_notification(db, notification_id, manual=True)
        return ok(
            {
                "id": item.id,
                "status": item.status,
                "attempt_count": item.attempt_count,
                "last_error_summary": item.last_error_summary,
            }
        )
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.get("/sop/versions", summary="售后 SOP 版本列表")
def sop_versions(
    db: Session = Depends(get_db),
    _payload=Depends(require_permission("aftersales:admin")),
):
    versions = db.query(AfterSalesSopVersion).order_by(AfterSalesSopVersion.created_at.desc()).all()
    return ok({"items": [_sop_data(item, db) for item in versions]})


@router.post("/sop/versions", summary="上传并解析售后 SOP")
async def upload_sop_version(
    version_no: str = Form(...),
    change_summary: str = Form(...),
    effective_date: date = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:admin")),
):
    user = _ark_user(db, payload)
    content = await file.read()
    try:
        version = create_sop_version(
            db,
            storage_root=_storage_root(),
            original_filename=file.filename or "sop.docx",
            content=content,
            version_no=version_no,
            change_summary=change_summary,
            effective_date=effective_date,
            uploaded_by_user_id=user.id,
        )
        db.commit()
        db.refresh(version)
        return ok(_sop_data(version, db), message="SOP 已解析，请确认后启用")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)


@router.post("/sop/versions/{version_id}/activate", summary="启用售后 SOP 版本")
def activate_sop(
    version_id: int,
    db: Session = Depends(get_db),
    payload=Depends(require_permission("aftersales:admin")),
):
    user = _ark_user(db, payload)
    try:
        version = activate_sop_version(db, version_id, user.id)
        db.commit()
        db.refresh(version)
        return ok(_sop_data(version, db), message="SOP 版本已启用")
    except Exception as exc:
        db.rollback()
        _to_http_error(exc)
