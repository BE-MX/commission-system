"""Agent acquisition endpoints scoped to search and unified research tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok, page_result
from app.knowledge import service as knowledge_service
from app.knowledge.models import KnowledgeLibrary
from app.sales_automation import public_pool_service, service
from app.sales_automation.dependencies import require_sales_agent
from app.sales_automation.router import _call, _iso, _job, _research_task, _user_id
from app.sales_automation.schemas import (
    AgentClaim,
    AgentFailure,
    AgentLease,
    CandidateBatch,
    PublicPoolIndustryGateSubmit,
    PublicPoolResearchSubmit,
)


router = APIRouter()


def _knowledge_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except knowledge_service.KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def _validate_knowledge_references(db: Session, agent: dict, references: list[dict]) -> None:
    for reference in references:
        try:
            document_id = int(reference["document_id"])
            revision_id = int(reference["revision_id"])
            version_no = int(reference["version_no"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, "企业知识库引用格式无效") from exc
        row = _knowledge_call(
            knowledge_service.get_published_document,
            db,
            agent,
            document_id,
            audit_action="sales_agent_research_reference",
        )
        if row["revision_id"] != revision_id or row["version_no"] != version_no:
            raise HTTPException(409, "企业知识库引用版本已变化，请重新读取后提交")
        library = db.query(KnowledgeLibrary).filter(
            KnowledgeLibrary.id == row.get("library_id"),
            KnowledgeLibrary.status == "active",
            KnowledgeLibrary.deleted_at.is_(None),
        ).one_or_none()
        if library is None or library.category != "company":
            raise HTTPException(409, "共享客户研究只能引用公司级知识库")


def _research_context(db: Session, task_id: int) -> dict:
    detail = _call(public_pool_service.get_task_detail, db, task_id)
    task = detail["task"]
    customer = detail["customer"]
    input_snapshot = dict(task.input_snapshot or {})
    if "customer_id" in input_snapshot:
        input_snapshot["customer_id"] = task.logical_customer_id
    return {
        "research_task_id": task.id,
        "customer_id": task.logical_customer_id,
        "task_type": task.task_type,
        "tier": task.tier,
        "policy_version": task.research_policy_version,
        "input_hash": public_pool_service.research_input_hash(task),
        "input_snapshot": input_snapshot,
        "customer": {
            "customer_id": customer.id,
            "customer_code": customer.customer_code,
            "display_name": customer.display_name,
            "canonical_company_name": customer.canonical_company_name,
            "identity_status": customer.identity_status,
            "relationship_stage": customer.relationship_stage,
        },
        "research_rules": {
            "identity_boundary": "仅围绕商业身份和公开业务证据调查；主体不明时保留待识别，不拼接同名主体资料",
            "industry_gate": "先验证业务相关性；明确无关时停止，不猜联系方式、不生成触达草稿或正向成交分",
            "required_evidence": ["source_record", "captured_at", "confidence"],
            "forbidden": ["猜测邮箱", "个人社会关系调查", "无来源事实", "跨客户读取", "直接触达"],
        },
    }


@router.get("/agent/knowledge/search")
def search_agent_knowledge(
    q: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    return ok(_knowledge_call(
        knowledge_service.search_published,
        db,
        agent,
        q,
        limit=limit,
        audit_action="sales_agent_knowledge_search",
    ))


@router.get("/agent/knowledge/documents/{document_id}")
def get_agent_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    return ok(_knowledge_call(
        knowledge_service.get_published_document,
        db,
        agent,
        document_id,
        audit_action="sales_agent_knowledge_read",
    ))


@router.get("/agent/research-tasks")
def list_agent_research_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    rows, total = public_pool_service.list_claimable_tasks(db, page, page_size)
    return ok(page_result([_research_task(row) for row in rows], total, page, page_size))


@router.get("/agent/research-tasks/{task_id}/context")
def get_agent_research_context(
    task_id: int,
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    return ok(_research_context(db, task_id))


@router.post("/agent/research-tasks/{task_id}/claim")
def claim_agent_research_task(
    task_id: int,
    payload: AgentClaim,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row, token = _call(
        public_pool_service.claim_task,
        db,
        task_id,
        _user_id(agent),
        payload.agent_id,
    )
    return ok({
        "research_task_id": row.id,
        "customer_id": row.logical_customer_id,
        "lease_token": token,
        "lease_generation": row.lease_generation,
        "input_hash": public_pool_service.research_input_hash(row),
    })


@router.post("/agent/research-tasks/{task_id}/heartbeat")
def heartbeat_agent_research_task(
    task_id: int,
    payload: AgentLease,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        public_pool_service.heartbeat_task,
        db,
        task_id,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    )
    return ok({"research_task_id": row.id, "lease_expires_at": _iso(row.lease_expires_at)})


@router.post("/agent/research-tasks/{task_id}/industry-gate")
def submit_agent_industry_gate(
    task_id: int,
    payload: PublicPoolIndustryGateSubmit,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        public_pool_service.submit_industry_gate,
        db,
        task_id,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
        payload.industry_relevance,
        payload.reason,
    )
    return ok({
        "research_task_id": row.id,
        "customer_id": row.logical_customer_id,
        "task_status": row.task_status,
        "gate_status": row.gate_status,
    })


@router.post("/agent/research-tasks/{task_id}/complete")
def complete_agent_research_task(
    task_id: int,
    payload: PublicPoolResearchSubmit,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    result_json = payload.result_json.model_dump(mode="json")
    references = result_json.get("knowledge_references") or []
    if references:
        _validate_knowledge_references(db, agent, references)
    row = _call(
        public_pool_service.complete_task_research,
        db,
        task_id,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
        result_json,
        agent_run_id=payload.agent_run_id,
        data_classification=payload.data_classification,
        visibility_scope=payload.visibility_scope,
    )
    return ok({
        "research_task_id": row.id,
        "customer_id": row.logical_customer_id,
        "task_status": row.task_status,
        "result_review_status": row.result_review_status,
        "evidence_fact_ids": row.evidence_fact_ids or [],
    })


@router.post("/agent/research-tasks/{task_id}/fail")
def fail_agent_research_task(
    task_id: int,
    payload: AgentFailure,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        public_pool_service.fail_task,
        db,
        task_id,
        payload.error_code,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    )
    return ok({
        "research_task_id": row.id,
        "customer_id": row.logical_customer_id,
        "task_status": row.task_status,
    })


@router.get("/agent/search-jobs")
def list_agent_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    rows, total = service.list_claimable_search_jobs(db, page, page_size)
    return ok(page_result([_job(row) for row in rows], total, page, page_size))


@router.get("/agent/search-jobs/{job_id}/context")
def get_agent_context(
    job_id: int,
    db: Session = Depends(get_db),
    _agent=Depends(require_sales_agent),
):
    row = _call(service.get_search_job, db, job_id)
    return ok({
        "job_id": row.id,
        "criteria_json": row.criteria_json or {},
        "profile_snapshot": row.profile_snapshot or {},
        "policy_version": row.policy_version,
        "profile_snapshot_hash": row.profile_snapshot_hash,
        "output_contract": {
            "identifier": "customer_id",
            "source_record_first": True,
            "company_name_nullable": True,
        },
    })


@router.post("/agent/search-jobs/{job_id}/claim")
def claim_search_job(
    job_id: int,
    payload: AgentClaim,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row, token = _call(service.claim_search_job, db, job_id, _user_id(agent), payload.agent_id)
    return ok({"job_id": row.id, "lease_token": token})


@router.post("/agent/search-jobs/{job_id}/heartbeat")
def heartbeat_search_job(
    job_id: int,
    payload: AgentLease,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        service.heartbeat_search_job,
        db,
        job_id,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    )
    return ok({"job_id": row.id, "lease_expires_at": _iso(row.lease_expires_at)})


@router.post("/agent/search-jobs/{job_id}/candidates")
def submit_candidates(
    job_id: int,
    payload: CandidateBatch,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    summary = _call(
        service.ingest_candidates,
        db,
        job_id,
        payload.candidates,
        payload.request_key,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    )
    return ok({"job_id": job_id, **summary})


@router.post("/agent/search-jobs/{job_id}/complete")
def complete_search_job(
    job_id: int,
    payload: AgentLease,
    db: Session = Depends(get_db),
    agent=Depends(require_sales_agent),
):
    row = _call(
        service.complete_search_job,
        db,
        job_id,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    )
    return ok({"job_id": row.id, "status": row.status})


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
        payload.error_code,
        _user_id(agent),
        payload.agent_id,
        payload.lease_token,
    )
    return ok({"job_id": row.id, "status": row.status})


__all__ = ["router"]
