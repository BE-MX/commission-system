"""智能获客 Agent 专用接口：可撤销 token + 短时任务租约。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok, page_result
from app.sales_automation import enrichment_service, service
from app.sales_automation.dependencies import require_sales_agent
from app.sales_automation.models import LeadContact
from app.sales_automation.router import _call, _company, _contact, _iso, _job, _user_id
from app.sales_automation.schemas import (
    AgentClaim,
    AgentFailure,
    AgentLease,
    CandidateBatch,
    ContactBatch,
    ResearchUpsert,
)


router = APIRouter()


@router.get("/agent/search-jobs")
def list_agent_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    job_status: str = Query("claimable", alias="status"),
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    rows, total = (
        service.list_claimable_search_jobs(db, page, page_size)
        if job_status == "claimable"
        else service.list_search_jobs(db, page, page_size, job_status)
    )
    return ok(page_result([_job(row) for row in rows], total, page, page_size))


@router.get("/agent/search-jobs/{job_id}/context")
def get_agent_context(
    job_id: int,
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    row = _call(service.get_search_job, db, job_id)
    return ok({
        "job": _job(row),
        "profile": row.profile_snapshot,
        "criteria": row.criteria,
        "output_contract": {
            "identity": "normalized company website domain",
            "required_fields": ["name", "website", "source_url", "captured_at"],
            "forbidden": ["invented company", "unsourced claim", "personal email guess"],
        },
    })


@router.post("/agent/search-jobs/{job_id}/claim")
def claim_search_job(
    job_id: int,
    payload: AgentClaim,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row, lease_token = _call(service.claim_search_job, db, job_id, _user_id(agent), payload.agent_id)
    return ok({"job": _job(row), "lease_token": lease_token, "lease_expires_at": _iso(row.lease_expires_at)})


@router.post("/agent/search-jobs/{job_id}/heartbeat")
def heartbeat_search_job(
    job_id: int,
    payload: AgentLease,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        service.heartbeat_search_job, db, job_id, _user_id(agent), payload.agent_id, payload.lease_token,
    )
    return ok({"lease_expires_at": _iso(row.lease_expires_at)})


@router.post("/agent/search-jobs/{job_id}/candidates")
def submit_candidates(
    job_id: int,
    payload: CandidateBatch,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    return ok(_call(
        service.ingest_candidates,
        db,
        job_id,
        payload.candidates,
        payload.request_key,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    ))


@router.post("/agent/search-jobs/{job_id}/complete")
def complete_search_job(
    job_id: int,
    payload: AgentLease,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        service.complete_search_job, db, job_id, _user_id(agent), payload.agent_id, payload.lease_token,
    )
    return ok(_job(row))


@router.post("/agent/search-jobs/{job_id}/fail")
def fail_search_job(
    job_id: int,
    payload: AgentFailure,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        service.fail_search_job,
        db,
        job_id,
        payload.error_message,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    )
    return ok(_job(row))


def _agent_lead_detail(db: Session, company_id: int) -> dict:
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
        "facts": [{
            "fact_type": fact.fact_type,
            "claim": fact.claim,
            "source_url": fact.source_url,
            "captured_at": _iso(fact.captured_at),
            "confidence": fact.confidence,
        } for fact in facts],
    }
    return data


@router.get("/agent/leads/{company_id}")
def get_agent_lead(
    company_id: int,
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    return ok(_agent_lead_detail(db, company_id))


@router.post("/agent/leads/{company_id}/contacts")
def save_contacts(
    company_id: int,
    payload: ContactBatch,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    rows = _call(enrichment_service.upsert_contacts, db, company_id, payload.contacts, _user_id(agent))
    return ok([_contact(row) for row in rows])


@router.post("/agent/leads/{company_id}/research")
def save_research(
    company_id: int,
    payload: ResearchUpsert,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(enrichment_service.upsert_research, db, company_id, payload, _user_id(agent))
    return ok({"id": row.id, "status": row.status, "finished_at": _iso(row.finished_at)})
