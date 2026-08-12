"""智能获客 Agent 专用接口：可撤销 token + 短时任务租约。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok, page_result
from app.sales_automation import enrichment_service, public_pool_service, service
from app.sales_automation.dependencies import require_sales_agent
from app.sales_automation.models import LeadContact, ResearchSubject
from app.sales_automation.router import (
    _assessment,
    _call,
    _company,
    _contact,
    _iso,
    _job,
    _pool_task,
    _subject,
    _user_id,
)
from app.sales_automation.schemas import (
    AgentClaim,
    AgentFailure,
    AgentLease,
    CandidateBatch,
    ContactBatch,
    PublicPoolResearchSubmit,
    ResearchUpsert,
)


router = APIRouter()


def _public_pool_context(db: Session, task_id: int) -> dict:
    detail = _call(public_pool_service.get_task_detail, db, task_id)
    task = detail["task"]
    subject = detail["subject"]
    assessment = detail["assessment"]
    return {
        "task": _pool_task(task, subject, assessment),
        "subject": _subject(subject),
        "trusted_seed": subject.source_snapshot or {},
        "research_rules": {
            "identity_boundary": "先用公司名、企业域名、官网、国家和历史订单确认主体；主体不明时标记 unverifiable，禁止拼接同名公司的资料",
            "tier_focus": {
                "T1": "优先核实历史合作、当前经营状态和可触发二次激活的变化",
                "T2": "围绕官网、企业邮箱或业务社媒核实产品匹配、采购角色和切换供应商诱因",
                "T3": "只有私人邮箱、电话或 WhatsApp 时先做轻量身份确认；缺少锚点时停止深挖",
            },
            "required_evidence": ["公开来源URL", "captured_at", "confidence"],
            "forbidden": ["猜测邮箱", "无来源事实", "跨主体拼接", "发送邮件或消息"],
        },
        "output_contract": {
            "identity_decisions": ["confirmed", "candidate", "unverifiable", "rejected"],
            "score_components": {
                "industry_fit": 25,
                "pain_switch_trigger": 20,
                "intent_reactivation": 20,
                "buying_capacity": 15,
                "reachability": 10,
                "timing": 10,
                "risk_penalty": 30,
            },
            "note": "成交等级和证据置信度由方舟后端重算；opening_message_en 仅保存为人工审核草稿",
        },
    }


@router.get("/agent/public-pool/tasks")
def list_agent_public_pool_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    rows, total = public_pool_service.list_claimable_tasks(db, page, page_size)
    subject_ids = {row.subject_id for row in rows}
    subjects = {
        row.id: row for row in db.query(ResearchSubject).filter(ResearchSubject.id.in_(subject_ids)).all()
    } if subject_ids else {}
    items = [_pool_task(row, subjects[row.subject_id], None) for row in rows if row.subject_id in subjects]
    return ok(page_result(items, total, page, page_size))


@router.get("/agent/public-pool/tasks/{task_id}/context")
def get_agent_public_pool_context(
    task_id: int,
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    return ok(_public_pool_context(db, task_id))


@router.post("/agent/public-pool/tasks/{task_id}/claim")
def claim_agent_public_pool_task(
    task_id: int,
    payload: AgentClaim,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row, lease_token = _call(
        public_pool_service.claim_task, db, task_id, _user_id(agent), payload.agent_id,
    )
    return ok({"task_id": row.id, "lease_token": lease_token, "lease_expires_at": _iso(row.lease_expires_at)})


@router.post("/agent/public-pool/tasks/{task_id}/heartbeat")
def heartbeat_agent_public_pool_task(
    task_id: int,
    payload: AgentLease,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        public_pool_service.heartbeat_task,
        db, task_id, _user_id(agent), payload.agent_id, payload.lease_token,
    )
    return ok({"lease_expires_at": _iso(row.lease_expires_at)})


@router.post("/agent/public-pool/tasks/{task_id}/complete")
def complete_agent_public_pool_task(
    task_id: int,
    payload: PublicPoolResearchSubmit,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    task, assessment = _call(public_pool_service.complete_task_research, db, task_id, payload, _user_id(agent))
    return ok({"task_id": task.id, "status": task.status, "assessment": _assessment(assessment)})


@router.post("/agent/public-pool/tasks/{task_id}/fail")
def fail_agent_public_pool_task(
    task_id: int,
    payload: AgentFailure,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        public_pool_service.fail_task,
        db, task_id, payload.error_message, _user_id(agent), payload.agent_id, payload.lease_token,
    )
    return ok({"task_id": row.id, "status": row.status, "error_message": row.error_message})


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
