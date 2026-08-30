"""Human-facing acquisition workflow endpoints using unified customer IDs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.customer.models import CustomerAssignment
from app.sales_automation import public_pool_service, service
from app.sales_automation.schemas import (
    ProfileUpsert,
    PublicPoolBatchCreate,
    QualificationReviewSubmit,
    ResearchResultReview,
    SearchJobCreate,
)


router = APIRouter()
READ_PERMISSIONS = ("sales_automation:read", "sales_automation:write", "sales_automation:admin")
WRITE_PERMISSIONS = ("sales_automation:write", "sales_automation:admin")


def _user_id(payload: dict) -> int:
    try:
        value = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误") from None
    if value <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误")
    return value


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _iso(value):
    return value.isoformat() if value is not None else None


def _safe_error_message(row):
    if not row.error_code:
        return None
    return service.AGENT_FAILURE_MESSAGES.get(
        row.error_code,
        "任务执行失败，请联系管理员查看安全日志",
    )


def _profile(row):
    if row is None:
        return None
    return {
        "id": row.id,
        "profile_key": row.profile_key,
        "company_name": row.company_name,
        "company_website": row.company_website,
        "products": row.products or [],
        "advantages": row.advantages or [],
        "target_countries": row.target_countries or [],
        "target_industries": row.target_industries or [],
        "target_roles": row.target_roles or [],
        "exclusions": row.exclusions or [],
        "default_language": row.default_language,
        "policy_version": row.policy_version,
        "policy_json": row.policy_json,
        "policy_snapshot_hash": row.policy_snapshot_hash,
        "policy_applied_at": _iso(row.policy_applied_at),
        "updated_at": _iso(row.updated_at),
    }


def _job(row):
    return {
        "job_id": row.id,
        "profile_id": row.profile_id,
        "name": row.name,
        "status": row.status,
        "adapter": row.adapter,
        "target_count": row.target_count,
        "criteria_json": row.criteria_json or {},
        "policy_version": row.policy_version,
        "profile_snapshot_hash": row.profile_snapshot_hash,
        "result_count": row.result_count,
        "created_customer_count": row.created_customer_count,
        "deduplicated_count": row.deduplicated_count,
        "researched_count": row.researched_count,
        "qualified_count": row.qualified_count,
        "cost_status": row.cost_status,
        "attempt_count": row.attempt_count,
        "error_code": row.error_code,
        "error_message": _safe_error_message(row),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _result(row):
    return {
        "result_id": row.id,
        "job_id": row.job_id,
        "customer_id": row.customer_id,
        "best_rank": row.best_rank,
        "best_score": float(row.best_score),
        "aggregated_score_reasons": row.aggregated_score_reasons or {},
        "result_status": row.result_status,
        "qualification_review_id": row.qualification_review_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _batch(row):
    return {
        "batch_id": row.id,
        "batch_date": row.batch_date.isoformat(),
        "policy_version": row.policy_version,
        "status": row.status,
        "quotas_json": row.quotas_json or {},
        "selection_snapshot": row.selection_snapshot or {},
        "result_counts": row.result_counts or {},
        "error_code": row.error_code,
        "error_message": _safe_error_message(row),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _research_task(row, *, include_content: bool = False):
    result = {
        "research_task_id": row.id,
        "customer_id": row.customer_id,
        "task_type": row.task_type,
        "source_ref_type": row.source_ref_type,
        "source_ref_id": row.source_ref_id,
        "tier": row.tier,
        "task_status": row.task_status,
        "gate_status": row.gate_status,
        "result_review_status": row.result_review_status,
        "research_policy_version": row.research_policy_version,
        "result_schema_version": row.result_schema_version,
        "data_classification": row.data_classification,
        "visibility_scope": row.visibility_scope,
        "content_redacted": not include_content,
        "attempt_count": row.attempt_count,
        "error_code": row.error_code,
        "error_message": _safe_error_message(row),
        "reviewed_by": row.reviewed_by,
        "reviewed_at": _iso(row.reviewed_at),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    if include_content:
        result.update({
            "selection_reason": row.selection_reason or [],
            "input_snapshot": row.input_snapshot or {},
            "result_json": row.result_json,
            "research_summary": row.research_summary,
            "evidence_fact_ids": row.evidence_fact_ids or [],
        })
    return result


def _can_view_research_content(db: Session, user: dict, row) -> bool:
    roles = set(user.get("roles") or [])
    permissions = set(user.get("permissions") or [])
    is_management = (
        "super_admin" in roles or "sales_automation:admin" in permissions
    )
    if row.data_classification == "restricted_internal" or row.visibility_scope == "management":
        return is_management
    if row.visibility_scope == "all_authorized":
        return True
    if row.visibility_scope != "customer_team":
        return False
    try:
        user_id = _user_id(user)
    except HTTPException:
        return False
    return db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == row.customer_id,
        CustomerAssignment.user_id == user_id,
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first() is not None or is_management


def _qualification(row):
    return {
        "qualification_review_id": row.id,
        "customer_id": row.customer_id,
        "review_version": row.review_version,
        "supersedes_review_id": row.supersedes_review_id,
        "review_source": row.review_source,
        "source_ref_id": row.source_ref_id,
        "decision": row.decision,
        "reason_code": row.reason_code,
        "reason_text": row.reason_text,
        "scope_type": row.scope_type,
        "scope_ref_id": row.scope_ref_id,
        "is_current": row.is_current,
        "policy_version": row.policy_version,
        "review_after": _iso(row.review_after),
        "reviewed_by": row.reviewed_by,
        "reviewed_at": _iso(row.reviewed_at),
    }


@router.get("/profile")
def get_profile(
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    return ok(_profile(service.get_profile(db)))


@router.put("/profile")
def save_profile(
    payload: ProfileUpsert,
    db: Session = Depends(get_db),
    user=Depends(require_permission("sales_automation:admin")),
):
    return ok(_profile(_call(service.upsert_profile, db, payload, _user_id(user))))


@router.get("/search-jobs")
def list_search_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = service.list_search_jobs(db, page, page_size, status_filter)
    return ok(page_result([_job(row) for row in rows], total, page, page_size))


@router.post("/search-jobs", status_code=status.HTTP_201_CREATED)
def create_search_job(
    payload: SearchJobCreate,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    return ok(_job(_call(service.create_search_job, db, payload, _user_id(user))))


@router.post("/search-jobs/{job_id}/requeue")
def requeue_search_job(
    job_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    return ok(_job(_call(service.requeue_search_job, db, job_id, _user_id(user))))


@router.get("/search-jobs/{job_id}/results")
def list_search_results(
    job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = _call(service.list_search_results, db, job_id, page, page_size)
    return ok(page_result([_result(row) for row in rows], total, page, page_size))


@router.get("/public-pool/audit")
def get_public_pool_audit(
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    return ok(_call(public_pool_service.latest_audit, db, False))


@router.post("/public-pool/audit/refresh")
def refresh_public_pool_audit(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("sales_automation:admin")),
):
    return ok(_call(public_pool_service.latest_audit, db, True))


@router.get("/public-pool/batches")
def list_public_pool_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = public_pool_service.list_batches(db, page, page_size)
    return ok(page_result([_batch(row) for row in rows], total, page, page_size))


@router.post("/public-pool/batches", status_code=status.HTTP_201_CREATED)
def create_public_pool_batch(
    payload: PublicPoolBatchCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("sales_automation:admin")),
):
    row = _call(public_pool_service.generate_batch, db, payload, _user_id(user))
    return ok(_batch(row))


@router.get("/research-tasks")
def list_research_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    batch_id: int | None = Query(None, ge=1),
    task_status: str | None = Query(None),
    tier: str | None = Query(None),
    result_review_status: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = public_pool_service.list_tasks(
        db,
        page,
        page_size,
        batch_id=batch_id,
        status=task_status,
        tier=tier,
        review_status=result_review_status,
    )
    return ok(page_result([_research_task(row) for row in rows], total, page, page_size))


@router.get("/research-tasks/{task_id}")
def get_research_task(
    task_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    row = _call(public_pool_service.get_task, db, task_id)
    return ok(_research_task(
        row,
        include_content=_can_view_research_content(db, user, row),
    ))


@router.post("/research-tasks/{task_id}/result-review")
def review_research_result(
    task_id: int,
    payload: ResearchResultReview,
    db: Session = Depends(get_db),
    user=Depends(require_permission("sales_automation:admin")),
):
    row = _call(
        public_pool_service.review_research_result,
        db,
        task_id,
        payload.review_status,
        reviewer_id=_user_id(user),
    )
    return ok(_research_task(row, include_content=True))


@router.get("/qualification-queue")
def list_qualification_queue(
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows = public_pool_service.list_pending_qualification(db)
    return ok({"items": [_research_task(row) for row in rows], "total": len(rows)})


@router.post("/qualification-reviews", status_code=status.HTTP_201_CREATED)
def submit_qualification_review(
    payload: QualificationReviewSubmit,
    db: Session = Depends(get_db),
    user=Depends(require_permission("sales_automation:admin")),
):
    data = payload.model_dump()
    row = _call(
        public_pool_service.submit_qualification_review,
        db,
        **data,
        reviewed_by=_user_id(user),
    )
    return ok(_qualification(row))


__all__ = [
    "READ_PERMISSIONS",
    "WRITE_PERMISSIONS",
    "_call",
    "_iso",
    "_job",
    "_research_task",
    "_user_id",
    "router",
]
