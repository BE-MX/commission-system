"""Server-owned external research runs and transactional evidence receipts.

The research task lease is the sole executor lease; these runs are never queued
for the native worker. Public observations remain candidate facts for review.
"""
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent_runtime.event_service import append_event, content_hash
from app.agent_runtime.models import AgentProfile, AgentRun, AgentSession
from app.core.time import beijing_now
from app.customer.models import CustomerAgentRunScope
from app.sales_automation import service

PROFILE = {
    "profile_key": "openclaw_customer_research", "version": 1,
    "name": "OpenClaw 客户背调", "description": "任务租约约束下的公开证据采集与人工审核",
    "runtime": "openclaw", "mode": "scheduled", "model_preset": "external_openclaw",
    "system_prompt": "只处理已领取任务；公开观察写为候选事实，逐条引用本次返回的证据，不猜测标识。",
    "skill_manifest": [{"name": "ark-company-research", "version": "2"}],
    "tool_allowlist": ["ark_append_research_facts"],
    "limits_json": {"max_attempts": 1},
    "policy_json": {"external_task_lease": True, "evidence_required": True},
    "output_schema": {"type": "object"},
}


def finish_run(db: Session, task, status: str, error_code: str | None = None):
    run = db.get(AgentRun, task.agent_run_id) if task.agent_run_id else None
    if run is None or run.source_runtime != "openclaw" or run.status != "running":
        return
    if (run.business_ref_type != "research_task" or run.business_ref_id != str(task.id)
            or (run.input_json or {}).get("customer_id") != task.customer_id):
        raise service.ConflictError("研究执行记录归属异常")
    run.status = status
    run.completed_at = beijing_now()
    session = db.get(AgentSession, run.session_id)
    if session is not None:
        session.status = "archived"
    run.error_code = error_code
    append_event(db, run, event_id=f"run-{run.id}-{status}", event_type=f"run.{status}",
                 actor_type="system", payload={"research_task_id": task.id, "error_code": error_code})


def start_run(db: Session, task, actor_id: int, input_hash: str):
    profile = db.query(AgentProfile).filter_by(profile_key=PROFILE["profile_key"], version=1).one_or_none()
    if profile is None or profile.status != "active":
        raise service.ConflictError("背调执行配置未初始化或已停用，请检查方舟服务启动")
    finish_run(db, task, "cancelled", "research_lease_reclaimed")
    now = beijing_now()
    session = AgentSession(owner_user_id=actor_id, profile_id=profile.id,
        title=f"客户背调 #{task.id} / {task.lease_generation}",
        context_type="research_task", context_id=str(task.id), status="active")
    db.add(session)
    db.flush()
    scope = {"research_task_id": task.id, "customer_id": task.customer_id,
             "input_hash": input_hash, "lease_generation": task.lease_generation}
    run = AgentRun(session_id=session.id, profile_id=profile.id, owner_user_id=actor_id,
        idempotency_key=f"research:{task.id}:lease:{task.lease_generation}",
        trigger_type="research_task", source_runtime="openclaw", mode="scheduled",
        business_ref_type="research_task", business_ref_id=str(task.id),
        input_json=scope, context_snapshot={**scope, "profile_key": profile.profile_key,
            "profile_version": profile.version, "owner_user_id": actor_id},
        status="running", max_attempts=1, started_at=now)
    db.add(run)
    db.flush()
    digest = content_hash({"run_id": run.id, **scope})
    db.add(CustomerAgentRunScope(run_id=run.id, customer_id=task.customer_id, scope_type="single",
        source_ref_type="research_task", source_ref_id=str(task.id), scope_snapshot_hash=digest,
        membership_fingerprint=content_hash({"run_id": run.id, "customer_id": task.customer_id,
                                            "scope_snapshot_hash": digest}), created_at=now))
    task.agent_run_id = run.id
    append_event(db, run, event_id=f"run-{run.id}-created", event_type="run.created",
                 actor_type="system", payload=scope)
    append_event(db, run, event_id=f"run-{run.id}-started", event_type="run.started",
                 actor_type="system", payload={"research_task_id": task.id})
    return run


def append_facts(db: Session, task_id: int, actor_id: int, agent_id: str,
                 lease_token: str, agent_run_id: int, facts):
    from app.sales_automation import enrichment_service, public_pool_service
    task, input_hash = public_pool_service.validate_research_fact_write(
        db, task_id, actor_id, agent_id, lease_token, agent_run_id)
    run = db.query(AgentRun).filter_by(id=agent_run_id).with_for_update().one()
    call_id = f"research-facts-{uuid4().hex}"
    append_event(db, run, event_id=f"{call_id}:requested", event_type="tool.requested",
        actor_type="system", payload={"call_id": call_id, "tool_name": "ark_append_research_facts",
            "research_task_id": task.id, "fact_count": len(facts)})
    _, rows = enrichment_service.append_research_facts(db, task.id, facts, agent_run_id=run.id)
    output = {"research_task_id": task.id, "customer_id": task.customer_id,
        "agent_run_id": run.id, "input_hash": input_hash, "tool_call_id": call_id,
        "evidence_refs": [{"customer_id": task.customer_id, "evidence_ref": f"fact:{fact.id}",
            "evidence_content_hash": fact.fact_fingerprint, "input_hash": input_hash,
            "data_classification": fact.data_classification, "visibility_scope": fact.visibility_scope}
            for fact in rows]}
    append_event(db, run, event_id=f"{call_id}:succeeded", event_type="tool.succeeded",
                 actor_type="system", payload={"call_id": call_id, "output": output})
    db.commit()
    return output


def requeue_failed_task(db: Session, task_id: int, actor_id: int, expected_attempt_count: int):
    """Human-authorized retry; preserve completed/skipped tasks and fence stale UI."""
    from app.sales_automation import public_pool_service
    public_pool_service._require_active_user(db, actor_id)
    task = public_pool_service.get_task(db, task_id, for_update=True)
    if task.logical_customer_id != task.customer_id:
        raise service.ConflictError("RESEARCH_TASK_LOGICAL_OWNER_CHANGED_RECREATE_REQUIRED")
    if task.task_status != "failed" or task.attempt_count != expected_attempt_count:
        raise service.ConflictError("仅可重试指定尝试次数的失败任务，请刷新状态")
    finish_run(db, task, "failed", task.error_code)
    task.task_status = "pending"
    task.gate_status = "pending"
    task.result_review_status = "pending"
    task.claimed_by = None
    task.lease_token_hash = None
    task.lease_expires_at = None
    # Error/result history remains until a new claim or gate replaces it. The new
    # lease generation changes input_hash and cannot consume the previous Run.
    db.commit()
    db.refresh(task)
    return task
