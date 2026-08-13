"""智能获客 Agent 专用接口：可撤销 token + 短时任务租约。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok, page_result
from app.knowledge import service as knowledge_service
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
    PublicPoolIndustryGateSubmit,
    ResearchUpsert,
)


router = APIRouter()


def _knowledge_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except knowledge_service.KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def _validate_knowledge_references(db: Session, agent: dict, references) -> None:
    for reference in references:
        row = _knowledge_call(
            knowledge_service.get_published_document,
            db,
            agent,
            reference.document_id,
            audit_action="sales_agent_research_reference",
        )
        if row["revision_id"] != reference.revision_id or row["version_no"] != reference.version_no:
            raise HTTPException(409, "企业知识库引用版本已变化，请重新读取后提交")


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
            "knowledge_baseline": "先检索当前账号可访问的已发布企业知识，确认目标行业、产品、优势、排除项与成交经验；知识库仅用于内部匹配判断，不是客户公开事实",
            "industry_gate": {
                "order": "先低成本核验实体、主营业务与目标行业相关性，再决定是否深挖",
                "irrelevant": "有可靠证据确认行业无关时立即停止，不再获取联系人/社会关系、不做供应商与深度风险评估、不生成触达草稿",
                "uncertain": "证据不足不等于行业无关；保留 uncertain，并沿社媒与弱线索轨做有限核验",
            },
            "social_first": "无独立站或官网贫乏时，将 Instagram、Facebook、TikTok、LinkedIn、Pinterest、YouTube、Google Business/预约页作为重点；核验账号互链、地点、业务内容和近期活跃度",
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
            "industry_relevance": ["core", "adjacent", "uncertain", "irrelevant"],
            "research_depth": ["gate_only", "focused", "deep"],
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


@router.get("/agent/knowledge/search")
def search_agent_knowledge(
    q: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    """Agent只读检索有ACL权限的已发布企业知识；草稿与待审版本不会返回。"""
    return ok(_knowledge_call(
        knowledge_service.search_published,
        db,
        agent,
        q,
        limit=limit,
        audit_action="sales_agent_research_search",
    ))


@router.get("/agent/knowledge/documents/{document_id}")
def get_agent_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    """Agent只读获取单篇有ACL权限的已发布知识正文。"""
    row = _knowledge_call(
        knowledge_service.get_published_document,
        db,
        agent,
        document_id,
        audit_action="sales_agent_research_read",
    )
    return ok({
        "document_id": row["document_id"],
        "revision_id": row["revision_id"],
        "title": row["title"],
        "content": row["content_text"],
        "version_no": row["version_no"],
    })


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


@router.post("/agent/public-pool/tasks/{task_id}/industry-gate")
def submit_agent_public_pool_industry_gate(
    task_id: int,
    payload: PublicPoolIndustryGateSubmit,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    """Two-stage stop-loss: only a passed gate authorizes the costly research phase."""
    _validate_knowledge_references(db, agent, payload.knowledge_references)
    task, can_deepen = _call(
        public_pool_service.submit_industry_gate, db, task_id, payload, _user_id(agent),
    )
    return ok({
        "task_id": task.id,
        "gate_status": task.gate_status,
        "deep_research_authorized": can_deepen,
        "status": task.status,
    })


@router.post("/agent/public-pool/tasks/{task_id}/complete")
def complete_agent_public_pool_task(
    task_id: int,
    payload: PublicPoolResearchSubmit,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    retried = _call(
        public_pool_service.get_idempotent_completed_research,
        db, task_id, payload, _user_id(agent),
    )
    if retried is not None:
        task, assessment = retried
        return ok({"task_id": task.id, "status": task.status, "assessment": _assessment(assessment)})
    _validate_knowledge_references(db, agent, payload.knowledge_references)
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
