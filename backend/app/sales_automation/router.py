"""智能获客 HTTP 接口。长任务由 Agent 异步执行，本路由只管理状态与结构化结果。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.knowledge import access as knowledge_access
from app.knowledge.models import KnowledgeDocument
from app.sales_automation import enrichment_service, public_pool_service, service
from app.sales_automation.models import DealAssessment, LeadContact, PublicPoolTask, ResearchRun, ResearchSubject
from app.sales_automation.schemas import (
    ProfileUpsert,
    PublicPoolBatchCreate,
    PublicPoolTaskReject,
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


def _profile(row):
    if row is None:
        return None
    return {
        "id": row.id,
        "company_name": row.company_name,
        "company_website": row.company_website,
        "products": row.products or [],
        "advantages": row.advantages or [],
        "target_countries": row.target_countries or [],
        "target_industries": row.target_industries or [],
        "target_roles": row.target_roles or [],
        "exclusions": row.exclusions or [],
        "default_language": row.default_language,
        "updated_at": _iso(row.updated_at),
    }


def _job(row):
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "adapter": row.adapter,
        "target_count": row.target_count,
        "criteria": row.criteria or {},
        "result_count": row.result_count,
        "created_count": row.created_count,
        "deduplicated_count": row.deduplicated_count,
        "public_pool_deduplicated_count": row.public_pool_deduplicated_count,
        "attempt_count": row.attempt_count,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _company(db: Session, row):
    contacts = db.query(LeadContact).filter(
        LeadContact.company_id == row.id,
        LeadContact.deleted_at.is_(None),
    ).all()
    research = db.query(ResearchRun).filter(
        ResearchRun.company_id == row.id,
        ResearchRun.deleted_at.is_(None),
    ).order_by(ResearchRun.created_at.desc()).first()
    lead_research = db.query(PublicPoolTask, ResearchSubject).join(
        ResearchSubject, ResearchSubject.id == PublicPoolTask.subject_id,
    ).filter(
        ResearchSubject.linked_company_id == row.id,
        ResearchSubject.subject_type == "lead_company",
        PublicPoolTask.deleted_at.is_(None),
        ResearchSubject.deleted_at.is_(None),
    ).order_by(PublicPoolTask.created_at.desc(), PublicPoolTask.id.desc()).first()
    duplicate_subject = db.query(ResearchSubject).filter(
        ResearchSubject.linked_company_id == row.id,
        ResearchSubject.source_system == "okki",
        ResearchSubject.deleted_at.is_(None),
    ).order_by(ResearchSubject.created_at.asc()).first()
    lead_research_task = lead_research[0] if lead_research is not None else None
    return {
        "id": row.id,
        "name": row.name,
        "domain": row.normalized_domain,
        "website": row.website,
        "country": row.country,
        "industry": row.industry,
        "description": row.description,
        "status": row.status,
        "match_score": row.match_score,
        "score_reasons": row.score_reasons or [],
        "owner_user_id": row.owner_user_id,
        "contact_count": len(contacts),
        "valid_email_count": sum(
            1 for item in contacts if item.email and item.email_status == "valid" and item.verified_at is not None
        ),
        "research_status": lead_research_task.status if lead_research_task is not None else (research.status if research else "pending"),
        "research_task_id": lead_research_task.id if lead_research_task is not None else None,
        "public_pool_duplicate": duplicate_subject is not None,
        "public_pool_subject_id": duplicate_subject.id if duplicate_subject is not None else None,
        "public_pool_customer_id": duplicate_subject.source_customer_id if duplicate_subject is not None else None,
        "approved_at": _iso(row.approved_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _contact(row):
    return {
        "id": row.id,
        "name": row.name,
        "role": row.role,
        "email": row.email,
        "email_status": row.email_status,
        "verified_at": _iso(row.verified_at),
        "source_provider": row.source_provider,
        "source_url": row.source_url,
        "captured_at": _iso(row.captured_at),
        "confidence": row.confidence,
    }


def _batch(row):
    return {
        "id": row.id,
        "batch_date": row.batch_date.isoformat(),
        "policy_version": row.policy_version,
        "status": row.status,
        "quota_per_tier": row.quota_per_tier,
        "quotas": row.quotas or {},
        "audit_snapshot": row.audit_snapshot or {},
        "profile_conditions": (row.audit_snapshot or {}).get("profile_conditions") or {},
        "result_counts": row.result_counts or {},
        "error_message": row.error_message,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
    }


def _subject(row: ResearchSubject):
    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "source_system": row.source_system,
        "linked_company_id": row.linked_company_id,
        "external_key": row.external_key,
        "source_customer_id": row.source_customer_id,
        "display_name": row.display_name,
        "country": row.country,
        "primary_email": row.primary_email,
        "email_domain_type": row.email_domain_type,
        "primary_phone": row.primary_phone,
        "website": row.website,
        "seed_tier": row.seed_tier,
        "completeness_score": row.completeness_score,
        "order_count": row.order_count,
        "order_amount_usd": float(row.order_amount_usd or 0),
        "last_order_at": _iso(row.last_order_at),
        "contact_snapshot": row.contact_snapshot or {},
        "source_snapshot": row.source_snapshot or {},
        "last_selected_at": _iso(row.last_selected_at),
    }


def _assessment(row: DealAssessment | None, *, include_knowledge_references: bool = False):
    if row is None:
        return None
    return {
        "id": row.id,
        "grade": row.grade,
        "deal_likelihood": row.deal_likelihood,
        "evidence_confidence": row.evidence_confidence,
        "identity_decision": row.identity_decision,
        "business_quality_score": row.business_quality_score,
        "deal_score": row.deal_score,
        "priority_score": row.priority_score,
        "score_factors": row.score_factors or {},
        "supplier_status": row.supplier_status,
        "pain_points": row.pain_points or [],
        "product_fit": row.product_fit or [],
        "industry_relevance": row.industry_relevance,
        "industry_relevance_reason": row.industry_relevance_reason,
        "research_depth": row.research_depth,
        "stop_reason": row.stop_reason,
        "social_profiles": row.social_profiles or [],
        "knowledge_references": (row.knowledge_references or []) if include_knowledge_references else [],
        "commercial_profile": row.commercial_profile or {},
        "recommended_strategy": row.recommended_strategy,
        "outreach_type": row.outreach_type,
        "opening_message_en": row.opening_message_en,
        "risks": row.risks or [],
        "evidence_snapshot": row.evidence_snapshot or {},
        "provider": row.provider,
        "model": row.model,
        "assessment_version": row.assessment_version,
        "completed_at": _iso(row.completed_at),
    }


def _pool_task(
    row: PublicPoolTask,
    subject: ResearchSubject,
    assessment: DealAssessment | None = None,
    opportunity=None,
):
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "tier": row.tier,
        "selection_rank": row.selection_rank,
        "selection_reason": row.selection_reason or [],
        "status": row.status,
        "review_status": row.review_status,
        "gate_status": row.gate_status,
        "attempt_count": row.attempt_count,
        "research_summary": row.research_summary,
        "error_message": row.error_message,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "reviewed_by": row.reviewed_by,
        "reviewed_at": _iso(row.reviewed_at),
        "opportunity_id": row.opportunity_id,
        "owner_user_id": opportunity.owner_user_id if opportunity is not None else None,
        "created_at": _iso(row.created_at),
        "subject": _subject(subject),
        "assessment": _assessment(assessment),
    }


def _authorized_knowledge_references(db: Session, user: dict, assessment: DealAssessment | None) -> list[dict]:
    """Never expose internal knowledge metadata through the broader sales read permission."""
    if assessment is None or not knowledge_access.has_platform(user, "knowledge:read"):
        return []
    result = []
    for item in assessment.knowledge_references or []:
        document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == item.get("document_id")).first()
        if document is None or not knowledge_access.can(db, user, document.library_id, "read"):
            continue
        result.append({
            "document_id": item.get("document_id"),
            "revision_id": item.get("revision_id"),
            "version_no": item.get("version_no"),
        })
    return result


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
    job_status: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = service.list_search_jobs(db, page, page_size, job_status)
    return ok(page_result([_job(row) for row in rows], total, page, page_size))


@router.post("/search-jobs", status_code=status.HTTP_201_CREATED)
def create_search_job(
    payload: SearchJobCreate,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    row = _call(service.create_search_job, db, payload, _user_id(user))
    from app.agent_runtime.orchestration import maybe_enqueue_sales_shadow
    maybe_enqueue_sales_shadow(db, row, user)
    return ok(_job(row), code=201)


@router.post("/search-jobs/{job_id}/requeue")
def requeue_search_job(
    job_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    return ok(_job(_call(service.requeue_search_job, db, job_id, _user_id(user))))


@router.get("/leads")
def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    lead_status: str | None = Query(None, alias="status"),
    keyword: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = service.list_leads(db, page, page_size, lead_status, keyword)
    return ok(page_result([_company(db, row) for row in rows], total, page, page_size))


@router.get("/leads/{company_id}")
def get_lead(
    company_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    row = _call(service.get_lead, db, company_id)
    contacts = db.query(LeadContact).filter(
        LeadContact.company_id == company_id,
        LeadContact.deleted_at.is_(None),
    ).order_by(LeadContact.created_at.asc()).all()
    research, facts = enrichment_service.get_latest_research(db, company_id)
    data = _company(db, row)
    data["contacts"] = [_contact(item) for item in contacts]
    data["research"] = None if research is None else {
        "id": research.id,
        "status": research.status,
        "summary": research.summary,
        "outreach_angles": research.outreach_angles or [],
        "risks": research.risks or [],
        "provider": research.provider,
        "model": research.model,
        "finished_at": _iso(research.finished_at),
        "facts": [{
            "id": fact.id,
            "fact_type": fact.fact_type,
            "claim": fact.claim,
            "source_url": fact.source_url,
            "captured_at": _iso(fact.captured_at),
            "confidence": fact.confidence,
        } for fact in facts],
    }
    if data["research_task_id"] is None:
        data["public_pool_research"] = None
    else:
        detail = _call(public_pool_service.get_task_detail, db, data["research_task_id"])
        deep_research = _pool_task(
            detail["task"], detail["subject"], detail["assessment"], detail["opportunity"],
        )
        run = detail["research_run"]
        deep_research["research"] = None if run is None else {
            "id": run.id,
            "summary": run.summary,
            "outreach_angles": run.outreach_angles or [],
            "risks": run.risks or [],
            "provider": run.provider,
            "model": run.model,
            "finished_at": _iso(run.finished_at),
            "facts": [{
                "id": fact.id,
                "fact_type": fact.fact_type,
                "claim": fact.claim,
                "source_url": fact.source_url,
                "captured_at": _iso(fact.captured_at),
                "confidence": fact.confidence,
            } for fact in detail["facts"]],
        }
        data["public_pool_research"] = deep_research
    return ok(data)


@router.post("/leads/{company_id}/approve")
def approve_lead(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    return ok(_company(db, _call(service.approve_lead, db, company_id, _user_id(user))))


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


@router.post("/public-pool/batches", status_code=status.HTTP_202_ACCEPTED)
def create_public_pool_batch(
    payload: PublicPoolBatchCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    row, should_start = _call(public_pool_service.prepare_batch, db, payload, _user_id(user))
    if should_start:
        background_tasks.add_task(public_pool_service.run_batch_in_background, row.id)
    return ok({**_batch(row), "enqueued": should_start}, code=202)


@router.get("/public-pool/tasks")
def list_public_pool_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task_status: str | None = Query(None, alias="status"),
    tier: str | None = Query(None),
    review_status: str | None = Query(None),
    allocation_status: str | None = Query(None, pattern="^(claimable|claimed)$"),
    keyword: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = public_pool_service.list_tasks(
        db, page, page_size, task_status, tier, review_status, allocation_status, keyword,
    )
    return ok(page_result(
        [_pool_task(task, subject, assessment, opportunity) for task, subject, assessment, opportunity in rows],
        total, page, page_size,
    ))


@router.get("/public-pool/tasks/{task_id}")
def get_public_pool_task(
    task_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*READ_PERMISSIONS)),
):
    detail = _call(public_pool_service.get_task_detail, db, task_id)
    data = _pool_task(detail["task"], detail["subject"], detail["assessment"], detail["opportunity"])
    if data["assessment"] is not None:
        data["assessment"]["knowledge_references"] = _authorized_knowledge_references(
            db, user, detail["assessment"],
        )
    data["contacts"] = [_contact(row) for row in detail["contacts"]]
    run = detail["research_run"]
    data["research"] = None if run is None else {
        "id": run.id,
        "summary": run.summary,
        "outreach_angles": run.outreach_angles or [],
        "risks": run.risks or [],
        "provider": run.provider,
        "model": run.model,
        "finished_at": _iso(run.finished_at),
        "facts": [{
            "id": fact.id,
            "fact_type": fact.fact_type,
            "claim": fact.claim,
            "source_url": fact.source_url,
            "captured_at": _iso(fact.captured_at),
            "confidence": fact.confidence,
        } for fact in detail["facts"]],
    }
    return ok(data)


@router.post("/public-pool/tasks/{task_id}/approve")
def approve_public_pool_task(
    task_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission("sales_automation:admin")),
):
    task = _call(public_pool_service.approve_task, db, task_id, _user_id(user))
    return ok({"task_id": task.id, "review_status": task.review_status, "reviewed_by": task.reviewed_by})


@router.post("/public-pool/tasks/{task_id}/claim")
def claim_public_pool_task(
    task_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    opportunity = _call(public_pool_service.claim_approved_task, db, task_id, _user_id(user))
    return ok({"task_id": task_id, "opportunity_id": opportunity.id, "owner_user_id": opportunity.owner_user_id})


@router.post("/public-pool/tasks/{task_id}/reject")
def reject_public_pool_task(
    task_id: int,
    payload: PublicPoolTaskReject,
    db: Session = Depends(get_db),
    user=Depends(require_permission("sales_automation:admin")),
):
    task = _call(public_pool_service.reject_task, db, task_id, _user_id(user), payload.reason)
    subject = db.query(ResearchSubject).filter(ResearchSubject.id == task.subject_id).first()
    return ok(_pool_task(task, subject))
