"""Customer-id public-pool research and qualification services."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import secrets
from typing import Any, Mapping

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.agent_runtime.models import AgentEvent, AgentRun
from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today, to_beijing_naive
from app.customer.models import (
    CustomerAccount,
    CustomerAnnotation,
    CustomerAssignment,
    CustomerFact,
    CustomerQualificationReview,
    CustomerResearchTask,
    CustomerSuppressionRegistry,
    CustomerTargetMatch,
    PublicPoolBatch,
    SearchJob,
    SearchResult,
)
from app.sales_automation import service
from app.sales_automation.schemas import CustomerResearchResult


LEASE_MINUTES = 15
ACTIVE_TASK_STATUSES = ("pending", "running")
CLASSIFICATION_ORDER = (
    "public_business",
    "internal_business",
    "personal_contact",
    "restricted_internal",
)
VISIBILITY_ORDER = ("all_authorized", "customer_team", "management")


def _data(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    return dict(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    source = value if isinstance(value, str) else _canonical_json(value)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def research_input_hash(task: CustomerResearchTask) -> str:
    return _hash({
        "schema_version": "research_execution_input_v1",
        "task_fingerprint": task.task_fingerprint,
        "lease_generation": int(task.lease_generation),
        "input_snapshot": task.input_snapshot or {},
    })


def _scope_filter(model, scope_type: str, scope_ref_id: str | None):
    return and_(
        model.scope_type == scope_type,
        model.scope_ref_id.is_(None) if scope_ref_id is None else model.scope_ref_id == scope_ref_id,
    )


def _require_active_user(db: Session, user_id: int) -> ArkUser:
    row = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).one_or_none()
    if row is None:
        raise service.ConflictError("审核用户不存在或已停用")
    return row


def default_profile_conditions() -> dict:
    """Stable default passed by the scheduler; values live in a policy snapshot."""
    return {
        "schema_version": "public_pool_selection_v1",
        "identity_statuses": ["identified", "verified"],
        "record_status": "active",
        "require_unassigned": True,
    }


def is_development_denied(
    db: Session,
    customer_id: int,
    scope_type: str = "global",
    scope_ref_id: str | None = None,
) -> bool:
    now = beijing_now()
    annotation = db.query(CustomerAnnotation.id).filter(
        CustomerAnnotation.customer_id == customer_id,
        CustomerAnnotation.annotation_type == "do_not_contact",
        CustomerAnnotation.status == "active",
        CustomerAnnotation.policy_effective_at <= now,
        or_(
            CustomerAnnotation.policy_scope_type == "global",
            and_(
                CustomerAnnotation.policy_scope_type == scope_type,
                CustomerAnnotation.policy_scope_ref_id.is_(None)
                if scope_ref_id is None
                else CustomerAnnotation.policy_scope_ref_id == scope_ref_id,
            ),
        ),
    ).first()
    if annotation is not None:
        return True
    suppression = db.query(CustomerSuppressionRegistry.id).filter(
        CustomerSuppressionRegistry.mapped_customer_id == customer_id,
        CustomerSuppressionRegistry.status == "active",
        CustomerSuppressionRegistry.effective_at <= now,
        or_(
            CustomerSuppressionRegistry.scope_type == "global",
            and_(
                CustomerSuppressionRegistry.scope_type == scope_type,
                CustomerSuppressionRegistry.scope_ref_id.is_(None)
                if scope_ref_id is None
                else CustomerSuppressionRegistry.scope_ref_id == scope_ref_id,
            ),
        ),
    ).first()
    return suppression is not None


def ensure_research_task(
    db: Session,
    *,
    customer_id: int,
    task_type: str,
    source_ref_type: str,
    source_ref_id: str,
    research_policy_version: str,
    input_snapshot: Mapping,
    selection_reason: list[dict],
    tier: str | None,
    created_by: int | None,
) -> tuple[CustomerResearchTask, bool]:
    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == customer_id,
        CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise service.NotFoundError("客户不存在")
    canonical_snapshot = _json_value(input_snapshot)
    fingerprint = _hash({
        "customer_id": customer_id,
        "task_type": task_type,
        "source_ref_type": source_ref_type,
        "source_ref_id": source_ref_id,
        "research_policy_version": research_policy_version,
        "input_snapshot": canonical_snapshot,
    })
    exact = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.task_fingerprint == fingerprint,
    ).one_or_none()
    if exact is not None:
        return exact, False
    active = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.customer_id == customer_id,
        CustomerResearchTask.task_type == task_type,
        CustomerResearchTask.research_policy_version == research_policy_version,
        or_(
            CustomerResearchTask.task_status.in_(ACTIVE_TASK_STATUSES),
            and_(
                CustomerResearchTask.task_status == "completed",
                CustomerResearchTask.result_review_status == "revision_requested",
            ),
        ),
    ).with_for_update().first()
    if active is not None:
        return active, False
    now = beijing_now()
    row = CustomerResearchTask(
        customer_id=customer_id,
        task_type=task_type,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        tier=tier,
        task_status="pending",
        gate_status="pending",
        result_review_status="pending",
        selection_reason=_json_value(selection_reason),
        research_policy_version=research_policy_version,
        task_fingerprint=fingerprint,
        input_snapshot=canonical_snapshot,
        result_schema_version=None,
        result_json=None,
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="versioned acquisition research policy",
        research_summary=None,
        evidence_fact_ids=[],
        lease_generation=0,
        attempt_count=0,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        exact = db.query(CustomerResearchTask).filter(
            CustomerResearchTask.task_fingerprint == fingerprint,
        ).one_or_none()
        if exact is None:
            raise
        return exact, False
    return row, True


def prepare_batch(db: Session, payload: Any, actor_id: int | None) -> tuple[PublicPoolBatch, bool]:
    data = _data(payload)
    batch_date = data.get("batch_date") or beijing_today()
    policy_version = str(data.get("policy_version") or "").strip()
    if not policy_version:
        raise service.SalesAutomationError("policy_version 必填")
    if "quotas_json" in data:
        quotas = _json_value(data["quotas_json"])
    else:
        quota = int(data.get("quota_per_tier") or 20)
        quotas = {
            "schema_version": "public_pool_quotas_v1",
            "tiers": {"T1": quota, "T2": quota, "T3": quota},
            "team_scope": "all",
            "total_limit": quota * 3,
        }
    selection_policy = _json_value(data.get("profile_conditions") or default_profile_conditions())
    watermark = db.query(CustomerAccount.id).order_by(CustomerAccount.id.desc()).limit(1).scalar() or 0
    idem = _hash({
        "batch_date": batch_date.isoformat(),
        "policy_version": policy_version,
        "quotas": quotas,
        "selection_policy": selection_policy,
        "input_watermark": watermark,
    })
    existing = db.query(PublicPoolBatch).filter(PublicPoolBatch.idempotency_key == idem).one_or_none()
    if existing is not None:
        return existing, False
    row = PublicPoolBatch(
        batch_date=batch_date,
        policy_version=policy_version,
        status="pending",
        quotas_json=quotas,
        selection_snapshot={
            "schema_version": "public_pool_selection_v1",
            "input_watermark": watermark,
            "policy": selection_policy,
            "candidate_count": None,
            "filter_counts": {},
        },
        result_counts={
            "schema_version": "public_pool_counts_v1",
            "selected": {},
            "created": {},
            "reused": {},
            "skipped": {},
            "failed": {},
        },
        idempotency_key=idem,
        created_by=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        # End the outer transaction so MySQL REPEATABLE READ opens a fresh
        # read view for the row that won the unique-key race.
        db.rollback()
        existing = db.query(PublicPoolBatch).filter(
            PublicPoolBatch.idempotency_key == idem,
        ).one_or_none()
        if existing is None:
            raise service.ConflictError("RETRY_NEW_TRANSACTION") from exc
        return existing, False
    db.commit()
    db.refresh(row)
    return row, True


def _tier_for_customer(db: Session, customer_id: int) -> str:
    match = db.query(CustomerTargetMatch).filter(
        CustomerTargetMatch.customer_id == customer_id,
        CustomerTargetMatch.is_current.is_(True),
    ).order_by(CustomerTargetMatch.match_score.desc()).first()
    if match is None:
        return "T3"
    score = Decimal(match.match_score)
    if score >= 80:
        return "T1"
    if score >= 60:
        return "T2"
    return "T3"


def execute_batch(db: Session, batch_id: int) -> PublicPoolBatch:
    batch = db.query(PublicPoolBatch).filter(PublicPoolBatch.id == batch_id).with_for_update().one_or_none()
    if batch is None:
        raise service.NotFoundError("公海批次不存在")
    if batch.status == "completed":
        return batch
    if batch.status not in {"pending", "failed"}:
        raise service.ConflictError("公海批次当前不可执行")
    batch.status = "running"
    batch.started_at = beijing_now()
    db.flush()
    active_primary_ids = {
        customer_id
        for (customer_id,) in db.query(CustomerAssignment.customer_id).filter(
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
        ).all()
    }
    selection_policy = dict((batch.selection_snapshot or {}).get("policy") or {})
    input_watermark = int((batch.selection_snapshot or {}).get("input_watermark") or 0)
    allowed_identity_statuses = set(
        selection_policy.get("identity_statuses") or ["identified", "verified"]
    )
    required_record_status = str(selection_policy.get("record_status") or "active")
    require_unassigned = bool(selection_policy.get("require_unassigned", True))
    candidates = db.query(CustomerAccount).filter(
        CustomerAccount.record_status == required_record_status,
        CustomerAccount.id <= input_watermark,
    ).order_by(CustomerAccount.id).all()
    quotas = dict((batch.quotas_json or {}).get("tiers") or {})
    total_limit = int((batch.quotas_json or {}).get("total_limit") or sum(
        max(0, int(value)) for value in quotas.values()
    ))
    selected = {"T1": 0, "T2": 0, "T3": 0}
    created = {"T1": 0, "T2": 0, "T3": 0}
    reused = {"T1": 0, "T2": 0, "T3": 0}
    skipped = {"T1": 0, "T2": 0, "T3": 0}
    filter_counts = {"identity_status": 0, "assigned": 0, "dnc": 0, "quota": 0}
    selected_customer_ids: list[int] = []
    research_task_ids: list[int] = []
    for account in candidates:
        if account.identity_status not in allowed_identity_statuses:
            filter_counts["identity_status"] += 1
            continue
        if require_unassigned and account.id in active_primary_ids:
            filter_counts["assigned"] += 1
            continue
        tier = _tier_for_customer(db, account.id)
        if is_development_denied(db, account.id, "source", "public_pool"):
            skipped[tier] += 1
            filter_counts["dnc"] += 1
            continue
        if (
            selected[tier] >= max(0, int(quotas.get(tier, 0)))
            or len(selected_customer_ids) >= total_limit
        ):
            filter_counts["quota"] += 1
            continue
        task, was_created = ensure_research_task(
            db,
            customer_id=account.id,
            task_type="public_pool",
            source_ref_type="public_pool_batch",
            source_ref_id=str(batch.id),
            research_policy_version=batch.policy_version,
            input_snapshot={
                "schema_version": "research_input_v1",
                "public_pool_batch_id": batch.id,
                "customer_id": account.id,
                "profile_input_seq": account.profile_input_seq,
            },
            selection_reason=[{"reason": "unassigned_public_pool", "tier": tier}],
            tier=tier,
            created_by=batch.created_by,
        )
        selected[tier] += 1
        created[tier] += int(was_created)
        reused[tier] += int(not was_created)
        selected_customer_ids.append(account.id)
        research_task_ids.append(task.id)
    batch.selection_snapshot = {
        **dict(batch.selection_snapshot or {}),
        "candidate_count": len(candidates),
        "filter_counts": filter_counts,
        "selected_customer_ids": selected_customer_ids,
        "research_task_ids": research_task_ids,
    }
    batch.result_counts = {
        "schema_version": "public_pool_counts_v1",
        "selected": selected,
        "created": created,
        "reused": reused,
        "skipped": skipped,
        "failed": {"T1": 0, "T2": 0, "T3": 0},
    }
    batch.status = "completed"
    batch.finished_at = beijing_now()
    batch.error_code = None
    batch.error_message = None
    db.commit()
    db.refresh(batch)
    return batch


def generate_batch(db: Session, payload: Any, actor_id: int | None) -> PublicPoolBatch:
    batch, should_execute = prepare_batch(db, payload, actor_id)
    return execute_batch(db, batch.id) if should_execute or batch.status in {"pending", "failed"} else batch


def run_batch_in_background(batch_id: int) -> None:
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        execute_batch(db, batch_id)


def latest_audit(db: Session, refresh: bool = False) -> dict:
    active_primary = db.query(CustomerAssignment.customer_id).filter(
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    )
    total = db.query(CustomerAccount).filter(CustomerAccount.record_status == "active").count()
    public_pool = db.query(CustomerAccount).filter(
        CustomerAccount.record_status == "active",
        ~CustomerAccount.id.in_(active_primary),
    ).count()
    blocked = sum(
        1 for (customer_id,) in db.query(CustomerAccount.id).filter(CustomerAccount.record_status == "active")
        if is_development_denied(db, customer_id, "source", "public_pool")
    )
    return {
        "schema_version": "public_pool_audit_v1",
        "generated_at": beijing_now().isoformat(),
        "total_customers": total,
        "unassigned_customers": public_pool,
        "development_blocked": blocked,
    }


def list_batches(db: Session, page: int, page_size: int) -> tuple[list[PublicPoolBatch], int]:
    query = db.query(PublicPoolBatch)
    total = query.count()
    rows = query.order_by(PublicPoolBatch.batch_date.desc(), PublicPoolBatch.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    return rows, total


def get_task(db: Session, task_id: int, *, for_update: bool = False) -> CustomerResearchTask:
    query = db.query(CustomerResearchTask).filter(CustomerResearchTask.id == task_id)
    if for_update:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise service.NotFoundError("研究任务不存在")
    return row


def list_tasks(
    db: Session,
    page: int,
    page_size: int,
    *,
    batch_id: int | None = None,
    status: str | None = None,
    tier: str | None = None,
    review_status: str | None = None,
    **_unused,
) -> tuple[list[CustomerResearchTask], int]:
    query = db.query(CustomerResearchTask)
    if batch_id is not None:
        query = query.filter(
            CustomerResearchTask.source_ref_type == "public_pool_batch",
            CustomerResearchTask.source_ref_id == str(batch_id),
        )
    if status:
        query = query.filter(CustomerResearchTask.task_status == status)
    if tier:
        query = query.filter(CustomerResearchTask.tier == tier)
    if review_status:
        query = query.filter(CustomerResearchTask.result_review_status == review_status)
    total = query.count()
    return (
        query.order_by(CustomerResearchTask.created_at.desc(), CustomerResearchTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all(),
        total,
    )


def list_claimable_tasks(db: Session, page: int, page_size: int) -> tuple[list[CustomerResearchTask], int]:
    now = beijing_now()
    query = db.query(CustomerResearchTask).filter(or_(
        CustomerResearchTask.task_status == "pending",
        and_(
            CustomerResearchTask.task_status == "running",
            CustomerResearchTask.lease_expires_at <= now,
        ),
        and_(
            CustomerResearchTask.task_status == "completed",
            CustomerResearchTask.result_review_status == "revision_requested",
        ),
    ))
    total = query.count()
    return (
        query.order_by(CustomerResearchTask.created_at, CustomerResearchTask.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all(),
        total,
    )


def _claim_owner(actor_id: int, agent_id: str) -> str:
    cleaned = str(agent_id or "").strip()
    if not cleaned or len(cleaned) > 96:
        raise service.SalesAutomationError("agent_id 必填且不超过96字符")
    return f"{actor_id}:{cleaned}"


def claim_task(
    db: Session,
    task_id: int,
    actor_id: int,
    agent_id: str,
) -> tuple[CustomerResearchTask, str]:
    task = get_task(db, task_id, for_update=True)
    now = beijing_now()
    reclaimable = (
        task.task_status == "running"
        and task.lease_expires_at is not None
        and task.lease_expires_at <= now
    )
    revision_requested = (
        task.task_status == "completed"
        and task.result_review_status == "revision_requested"
    )
    if task.task_status != "pending" and not reclaimable and not revision_requested:
        raise service.ConflictError("研究任务不是等待领取状态，或租约仍有效")
    token = secrets.token_urlsafe(32)
    task.task_status = "running"
    task.result_review_status = "pending"
    task.reviewed_by = None
    task.reviewed_at = None
    task.claimed_by = _claim_owner(actor_id, agent_id)
    task.lease_generation += 1
    task.lease_token_hash = _hash(token)
    task.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    task.attempt_count += 1
    task.started_at = task.started_at or beijing_now()
    task.finished_at = None
    task.error_code = None
    task.error_message = None
    db.commit()
    db.refresh(task)
    return task, token


def _leased_task(
    db: Session,
    task_id: int,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> CustomerResearchTask:
    task = get_task(db, task_id, for_update=True)
    if task.claimed_by != _claim_owner(actor_id, agent_id):
        raise service.ConflictError("研究任务租约不属于当前Agent")
    if not lease_token or not secrets.compare_digest(task.lease_token_hash or "", _hash(lease_token)):
        raise service.ConflictError("研究任务租约无效")
    if task.lease_expires_at is None or task.lease_expires_at <= beijing_now():
        raise service.ConflictError("研究任务租约已过期")
    if task.task_status != "running":
        raise service.ConflictError("研究任务不在执行中")
    return task


def heartbeat_task(
    db: Session,
    task_id: int,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> CustomerResearchTask:
    task = _leased_task(db, task_id, actor_id, agent_id, lease_token)
    task.lease_expires_at = beijing_now() + timedelta(minutes=LEASE_MINUTES)
    db.commit()
    db.refresh(task)
    return task


def submit_industry_gate(
    db: Session,
    task_id: int,
    actor_id: int,
    agent_id: str,
    lease_token: str,
    industry_relevance: str,
    reason: str,
) -> CustomerResearchTask:
    task = _leased_task(db, task_id, actor_id, agent_id, lease_token)
    if task.gate_status != "pending":
        raise service.ConflictError("行业门控已提交")
    cleaned_reason = str(reason or "").strip()
    if not cleaned_reason:
        raise service.SalesAutomationError("行业门控原因必填")
    if industry_relevance == "irrelevant":
        task.gate_status = "stopped"
        task.task_status = "skipped"
        task.result_review_status = "not_required"
        task.result_schema_version = "research_gate_v1"
        task.result_json = {
            "schema_version": "research_gate_v1",
            "industry_relevance": "irrelevant",
            "stop_reason": cleaned_reason,
        }
        task.research_summary = cleaned_reason
        task.finished_at = beijing_now()
        task.claimed_by = None
        task.lease_token_hash = None
        task.lease_expires_at = None
    elif industry_relevance in {"core", "adjacent", "uncertain"}:
        task.gate_status = "passed"
        task.result_schema_version = "research_gate_v1"
        task.result_json = {
            "schema_version": "research_gate_v1",
            "industry_relevance": industry_relevance,
            "gate_reason": cleaned_reason,
        }
    else:
        raise service.SalesAutomationError("industry_relevance 无效")
    db.commit()
    db.refresh(task)
    return task


def _validate_research_run_and_citations(
    db: Session,
    task: CustomerResearchTask,
    actor_id: int,
    agent_run_id: int,
    input_hash: str,
    facts_by_id: dict[int, CustomerFact],
    citations: list[dict],
) -> AgentRun:
    run = db.query(AgentRun).filter(AgentRun.id == agent_run_id).one_or_none()
    run_input = dict(run.input_json or {}) if run is not None else {}
    run_context = dict(run.context_snapshot or {}) if run is not None else {}
    if (
        run is None
        or run.owner_user_id != actor_id
        or run.status not in {"running", "completed"}
        or run.business_ref_type != "research_task"
        or run.business_ref_id != str(task.id)
        or run_input.get("research_task_id") != task.id
        or run_input.get("customer_id") != task.customer_id
        or run_input.get("input_hash") != input_hash
        or run_context.get("customer_id") != task.customer_id
        or run_context.get("input_hash") != input_hash
    ):
        raise service.ConflictError("受控Agent Run与当前研究任务或input_hash不匹配")

    events = db.query(AgentEvent).filter(
        AgentEvent.run_id == run.id,
        AgentEvent.event_type.in_(("tool.requested", "tool.succeeded")),
    ).order_by(AgentEvent.sequence_no).all()
    requested: set[str] = set()
    succeeded: dict[str, list[dict]] = {}
    for event in events:
        payload = event.payload_json or {}
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            continue
        if event.event_type == "tool.requested":
            requested.add(call_id)
        else:
            refs = payload.get("evidence_refs") or []
            succeeded[call_id] = [item for item in refs if isinstance(item, Mapping)]

    now = beijing_now()
    for citation in citations:
        call_id = citation["tool_call_id"]
        if call_id not in requested or call_id not in succeeded:
            raise service.ConflictError("研究citation未关联当前Run的成功工具调用")
        fact_id = int(citation["evidence_ref"].split(":", 1)[1])
        fact = facts_by_id[fact_id]
        if fact.fact_fingerprint != citation["evidence_content_hash"]:
            raise service.ConflictError("研究citation证据内容哈希已变化")
        if fact.verification_status in {"disputed", "rejected", "superseded"}:
            raise service.ConflictError("研究citation引用的事实已失效")
        if fact.effective_to is not None and to_beijing_naive(fact.effective_to) <= now:
            raise service.ConflictError("研究citation引用的事实已过期")
        if fact.expires_at is not None and to_beijing_naive(fact.expires_at) <= now:
            raise service.ConflictError("研究citation引用的事实已过期")
        expected = {
            "customer_id": task.customer_id,
            "evidence_ref": citation["evidence_ref"],
            "evidence_content_hash": citation["evidence_content_hash"],
            "input_hash": input_hash,
        }
        if not any(all(reference.get(key) == value for key, value in expected.items())
                   for reference in succeeded[call_id]):
            raise service.ConflictError("研究citation不在当前Run实际返回的证据集合中")
    return run


def complete_task_research(
    db: Session,
    task_id: int,
    actor_id: int,
    agent_id: str,
    lease_token: str,
    result_json: Mapping,
    *,
    agent_run_id: int,
    data_classification: str = "internal_business",
    visibility_scope: str = "customer_team",
) -> CustomerResearchTask:
    task = _leased_task(db, task_id, actor_id, agent_id, lease_token)
    if task.gate_status not in {"passed", "not_required"}:
        raise service.ConflictError("行业门控未通过，不能提交完整研究")
    try:
        contract = CustomerResearchResult.model_validate(result_json)
    except ValidationError as exc:
        raise service.ConflictError("customer_research_v1结构、claim或citation无效") from exc
    result = contract.model_dump(mode="json")
    input_hash = research_input_hash(task)
    if result["input_hash"] != input_hash:
        raise service.ConflictError("customer_research_v1.input_hash与当前任务不匹配")
    normalized_fact_ids = sorted({
        int(citation["evidence_ref"].split(":", 1)[1])
        for citation in result["citations"]
    })
    facts = db.query(CustomerFact).filter(CustomerFact.id.in_(normalized_fact_ids)).all() \
        if normalized_fact_ids else []
    if len(facts) != len(normalized_fact_ids) or any(
        fact.customer_id != task.customer_id for fact in facts
    ):
        raise service.ConflictError("研究证据事实不属于当前客户或不存在")
    facts_by_id = {fact.id: fact for fact in facts}
    run = _validate_research_run_and_citations(
        db,
        task,
        actor_id,
        agent_run_id,
        input_hash,
        facts_by_id,
        result["citations"],
    )
    classifications = [task.data_classification, data_classification]
    classifications.extend(fact.data_classification for fact in facts)
    visibilities = [task.visibility_scope, visibility_scope]
    visibilities.extend(fact.visibility_scope for fact in facts)
    if any(value not in CLASSIFICATION_ORDER for value in classifications):
        raise service.SalesAutomationError("研究数据分级无效")
    if any(value not in VISIBILITY_ORDER for value in visibilities):
        raise service.SalesAutomationError("研究可见范围无效")
    strictest_classification = max(classifications, key=CLASSIFICATION_ORDER.index)
    strictest_visibility = max(visibilities, key=VISIBILITY_ORDER.index)
    result["evidence_fact_ids"] = normalized_fact_ids
    task.task_status = "completed"
    task.result_review_status = "pending"
    task.result_schema_version = "customer_research_v1"
    task.result_json = result
    task.research_summary = "；".join(
        claim["statement"] for claim in result["claims"]
    )[:10000]
    task.evidence_fact_ids = normalized_fact_ids
    task.agent_run_id = run.id
    task.data_classification = strictest_classification
    task.visibility_scope = strictest_visibility
    task.classification_reason = "strictest classification inherited from task, caller and evidence facts"
    task.finished_at = beijing_now()
    task.claimed_by = None
    task.lease_token_hash = None
    task.lease_expires_at = None
    db.commit()
    db.refresh(task)
    return task


def fail_task(
    db: Session,
    task_id: int,
    error_code: str,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> CustomerResearchTask:
    task = _leased_task(db, task_id, actor_id, agent_id, lease_token)
    safe_message = service.agent_failure_message(error_code)
    task.task_status = "failed"
    task.error_code = str(error_code)
    task.error_message = safe_message
    task.finished_at = beijing_now()
    task.claimed_by = None
    task.lease_token_hash = None
    task.lease_expires_at = None
    db.commit()
    db.refresh(task)
    return task


def review_research_result(
    db: Session,
    task_id: int,
    review_status: str,
    *,
    reviewer_id: int,
) -> CustomerResearchTask:
    _require_active_user(db, reviewer_id)
    if review_status not in {"accepted", "revision_requested", "rejected"}:
        raise service.SalesAutomationError("研究质量审核状态无效")
    task = get_task(db, task_id, for_update=True)
    if task.task_status != "completed":
        raise service.ConflictError("只有已完成研究可进行质量审核")
    task.result_review_status = review_status
    task.reviewed_by = reviewer_id
    task.reviewed_at = beijing_now()
    db.commit()
    db.refresh(task)
    return task


def _qualification_reference_customer(
    db: Session,
    review_source: str,
    source_ref_id: str | None,
) -> int | None:
    if review_source == "search_result":
        if not str(source_ref_id or "").isdigit():
            raise service.ConflictError("资格审核来源对象无效")
        row = db.get(SearchResult, int(source_ref_id))
        if row is None:
            raise service.ConflictError("资格审核来源对象不存在")
        return row.customer_id
    if review_source == "public_pool_research":
        if not str(source_ref_id or "").isdigit():
            raise service.ConflictError("资格审核来源对象无效")
        row = db.query(CustomerResearchTask).filter(
            CustomerResearchTask.id == int(source_ref_id),
        ).with_for_update().one_or_none()
        if row is None:
            raise service.ConflictError("资格审核来源对象不存在")
        return row.customer_id
    if review_source in {"manual", "identity_conflict"}:
        return None
    raise service.SalesAutomationError("review_source 无效")


def current_qualification(
    db: Session,
    customer_id: int,
    scope_type: str,
    scope_ref_id: str | None,
) -> CustomerQualificationReview | None:
    return db.query(CustomerQualificationReview).filter(
        CustomerQualificationReview.customer_id == customer_id,
        CustomerQualificationReview.is_current.is_(True),
        _scope_filter(CustomerQualificationReview, scope_type, scope_ref_id),
    ).one_or_none()


def _qualification_request_hash(
    *,
    customer_id: int,
    review_source: str,
    source_ref_id: str | None,
    decision: str,
    reason_code: str,
    scope_type: str,
    scope_ref_id: str | None,
    review_snapshot: Mapping,
    client_request_key: str,
) -> str:
    return _hash({
        "customer_id": customer_id,
        "review_source": review_source,
        "source_ref_id": source_ref_id,
        "decision": decision,
        "reason_code": reason_code,
        "scope_type": scope_type,
        "scope_ref_id": scope_ref_id,
        "review_snapshot": review_snapshot,
        "client_request_key": client_request_key,
    })


def submit_qualification_review(
    db: Session,
    *,
    customer_id: int,
    review_source: str,
    source_ref_id: str | None,
    decision: str,
    reason_code: str,
    scope_type: str,
    scope_ref_id: str | None,
    policy_version: str,
    review_snapshot: Mapping,
    decision_request_key: str,
    reviewed_by: int,
    expected_current_review_id: int | None,
    reason_text: str | None = None,
    review_after: datetime | None = None,
) -> CustomerQualificationReview:
    reviewer = _require_active_user(db, reviewed_by)
    if decision not in {"approved", "rejected", "deferred"}:
        raise service.SalesAutomationError("decision 无效")
    if reason_code not in {
        "qualified", "not_now", "poor_fit", "wrong_identity",
        "duplicate", "do_not_contact", "bad_data",
    }:
        raise service.SalesAutomationError("reason_code 无效")
    if scope_type not in {"global", "target_profile", "product", "market", "source", "channel"}:
        raise service.SalesAutomationError("scope_type 无效")
    if scope_type == "global" and scope_ref_id is not None:
        raise service.SalesAutomationError("global范围不得包含scope_ref_id")
    if scope_type != "global" and not str(scope_ref_id or "").strip():
        raise service.SalesAutomationError("非global范围必须包含scope_ref_id")
    if reason_code == "poor_fit" and scope_type == "global":
        raise service.SalesAutomationError("poor_fit必须限定目标画像、产品或市场范围")
    if decision == "approved" and reason_code != "qualified":
        raise service.SalesAutomationError("approved必须使用qualified原因")
    if reason_code == "do_not_contact" and decision != "rejected":
        raise service.SalesAutomationError("do_not_contact必须是rejected结论")
    referenced_customer = _qualification_reference_customer(db, review_source, source_ref_id)
    if referenced_customer is not None and referenced_customer != customer_id:
        raise service.ConflictError("资格审核来源对象不属于当前客户")
    if review_source == "public_pool_research":
        research = db.get(CustomerResearchTask, int(source_ref_id))
        if (
            research.task_status != "completed"
            or research.gate_status != "passed"
            or research.result_review_status != "accepted"
        ):
            raise service.ConflictError("研究成果尚未完成质量审核")
    normalized_review_after = (
        to_beijing_naive(review_after) if review_after is not None else None
    )
    now = beijing_now()
    if normalized_review_after is not None and normalized_review_after <= now:
        raise service.SalesAutomationError("review_after必须是未来的北京时间")
    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == customer_id,
        CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise service.NotFoundError("客户不存在")
    if (
        decision == "approved"
        and review_source in {"search_result", "public_pool_research"}
        and account.current_profile_version_id is None
    ):
        raise service.ConflictError("PROFILE_NOT_READY")
    request_hash = _qualification_request_hash(
        customer_id=customer_id,
        review_source=review_source,
        source_ref_id=source_ref_id,
        decision=decision,
        reason_code=reason_code,
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        review_snapshot=review_snapshot,
        client_request_key=str(decision_request_key),
    )
    replay = db.query(CustomerQualificationReview).filter(
        CustomerQualificationReview.decision_request_key == request_hash,
    ).one_or_none()
    if replay is not None:
        if replay.customer_id != customer_id:
            raise service.ConflictError("资格审核幂等键冲突")
        return replay
    current = current_qualification(db, customer_id, scope_type, scope_ref_id)
    actual_current_id = current.id if current is not None else None
    if actual_current_id != expected_current_review_id:
        raise service.ConflictError("当前作用范围资格结论已变化，请刷新后重试")
    if decision == "approved" and is_development_denied(db, customer_id, scope_type, scope_ref_id):
        raise service.ConflictError("客户当前存在禁止开发策略")
    if current is not None:
        current.is_current = False
        db.flush()
    row = CustomerQualificationReview(
        customer_id=customer_id,
        review_version=(current.review_version + 1) if current is not None else 1,
        supersedes_review_id=current.id if current is not None else None,
        review_source=review_source,
        source_ref_id=source_ref_id,
        decision=decision,
        reason_code=reason_code,
        reason_text=reason_text,
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        is_current=True,
        policy_version=policy_version,
        review_after=normalized_review_after,
        review_snapshot=_json_value(review_snapshot),
        decision_request_key=request_hash,
        reviewed_by=reviewer.id,
        reviewed_at=now,
        created_at=now,
    )
    db.add(row)
    db.flush()
    if reason_code == "do_not_contact":
        existing_dnc = db.query(CustomerAnnotation).filter(
            CustomerAnnotation.customer_id == customer_id,
            CustomerAnnotation.annotation_type == "do_not_contact",
            CustomerAnnotation.status == "active",
            CustomerAnnotation.policy_scope_type == scope_type,
            CustomerAnnotation.policy_scope_ref_id.is_(None)
            if scope_ref_id is None
            else CustomerAnnotation.policy_scope_ref_id == scope_ref_id,
        ).one_or_none()
        if existing_dnc is None:
            db.add(CustomerAnnotation(
                customer_id=customer_id,
                annotation_type="do_not_contact",
                target_fact_id=None,
                content_schema_version="v1",
                content_json={
                    "reason": reason_text or "qualification_review",
                    "qualification_review_id": row.id,
                },
                policy_scope_type=scope_type,
                policy_scope_ref_id=scope_ref_id,
                policy_effective_at=now,
                visibility="management",
                data_classification="restricted_internal",
                status="active",
                authored_by=reviewer.id,
                created_at=now,
                updated_at=now,
            ))
    if review_source == "search_result" and str(source_ref_id or "").isdigit():
        result = db.get(SearchResult, int(source_ref_id))
        if result is not None:
            result.qualification_review_id = row.id
            result.result_status = {
                "approved": "qualified",
                "rejected": "rejected",
                "deferred": "active",
            }[decision]
            job = db.get(SearchJob, result.job_id)
            if job is not None:
                db.flush()
                qualified = db.query(SearchResult).filter(
                    SearchResult.job_id == job.id,
                    SearchResult.result_status == "qualified",
                ).count()
                job.qualified_count = qualified
    if review_source in {"search_result", "public_pool_research"}:
        from app.customer.workflow_service import (
            CustomerWorkflowError,
            orchestrate_qualification_review,
        )

        try:
            orchestrate_qualification_review(db, row.id)
        except CustomerWorkflowError as exc:
            raise service.ConflictError(str(exc)) from exc
    account.profile_input_seq += 1
    account.updated_by = reviewer.id
    account.updated_at = now
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = db.query(CustomerQualificationReview).filter(
            CustomerQualificationReview.decision_request_key == request_hash,
        ).one_or_none()
        if replay is not None:
            return replay
        raise service.ConflictError("当前作用范围资格结论已被并发更新") from exc
    db.refresh(row)
    return row


def list_pending_qualification(db: Session) -> list[CustomerResearchTask]:
    tasks = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.task_status == "completed",
        CustomerResearchTask.result_review_status == "accepted",
    ).order_by(CustomerResearchTask.created_at, CustomerResearchTask.id).all()
    pending: list[CustomerResearchTask] = []
    for task in tasks:
        review_source = "public_pool_research" if task.task_type == "public_pool" else "search_result"
        source_ref_id = str(task.id) if review_source == "public_pool_research" else task.source_ref_id
        exists = db.query(CustomerQualificationReview.id).filter(
            CustomerQualificationReview.customer_id == task.customer_id,
            CustomerQualificationReview.review_source == review_source,
            CustomerQualificationReview.source_ref_id == source_ref_id,
            CustomerQualificationReview.is_current.is_(True),
        ).first()
        if exists is None:
            pending.append(task)
    return pending


def get_task_detail(db: Session, task_id: int) -> dict:
    task = get_task(db, task_id)
    account = db.get(CustomerAccount, task.customer_id)
    return {"task": task, "customer": account}


__all__ = [
    "claim_task",
    "complete_task_research",
    "current_qualification",
    "default_profile_conditions",
    "ensure_research_task",
    "execute_batch",
    "fail_task",
    "generate_batch",
    "get_task",
    "get_task_detail",
    "heartbeat_task",
    "is_development_denied",
    "latest_audit",
    "list_batches",
    "list_claimable_tasks",
    "list_pending_qualification",
    "list_tasks",
    "prepare_batch",
    "research_input_hash",
    "review_research_result",
    "run_batch_in_background",
    "submit_industry_gate",
    "submit_qualification_review",
]
