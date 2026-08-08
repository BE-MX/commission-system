"""智能获客 HTTP 接口。长任务由 Agent 异步执行，本路由只管理状态与结构化结果。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.sales_automation import enrichment_service, service
from app.sales_automation.models import LeadContact, ResearchRun
from app.sales_automation.schemas import (
    ProfileUpsert,
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
        "research_status": research.status if research else "pending",
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
    return ok(data)


@router.post("/leads/{company_id}/approve")
def approve_lead(
    company_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    return ok(_company(db, _call(service.approve_lead, db, company_id, _user_id(user))))
