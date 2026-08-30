"""Unified customer-id acquisition search workflow."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import secrets
from typing import Any, Mapping

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.customer.fact_service import append_source_record
from app.customer.identity_service import (
    CustomerDomainError,
    CustomerTransactionRetryRequired,
    IdentityCandidate,
    resolve_business_context,
)
from app.customer.models import (
    CustomerAccount,
    CustomerResearchTask,
    PublicPoolBatch,
    SearchJob,
    SearchResult,
    SearchResultSource,
)
from app.customer.logical_customer_service import logical_owner_expression, logical_root_predicate
from app.sales_automation.identity import InvalidExternalUrl, normalize_domain, normalize_source_url
from app.sales_automation.models import AcquisitionProfile


class SalesAutomationError(ValueError):
    pass


class NotFoundError(SalesAutomationError):
    pass


class ConflictError(SalesAutomationError):
    pass


LEASE_MINUTES = 15
AGENT_FAILURE_MESSAGES = {
    "provider_unavailable": "外部服务暂时不可用，请稍后重试",
    "provider_rate_limited": "外部服务请求过于频繁，请稍后重试",
    "invalid_provider_response": "外部服务返回无效，请稍后重试",
    "agent_execution_failed": "Agent执行失败，请重新领取任务后重试",
}


def _data(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    return dict(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return to_beijing_naive(value).isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash(value: Any) -> str:
    source = value if isinstance(value, str) else _canonical_json(value)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def agent_failure_message(error_code: str) -> str:
    try:
        return AGENT_FAILURE_MESSAGES[str(error_code)]
    except KeyError as exc:
        raise SalesAutomationError("Agent失败码无效") from exc


def _datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return to_beijing_naive(value)
    if isinstance(value, str):
        try:
            return to_beijing_naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError as exc:
            raise SalesAutomationError(f"{field} 格式无效") from exc
    raise SalesAutomationError(f"{field} 必填")


def _score(value: Any) -> Decimal:
    try:
        score = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise SalesAutomationError("score 格式无效") from exc
    if score < 0 or score > 100:
        raise SalesAutomationError("score 必须在0至100之间")
    return score


def _policy_snapshot(profile: AcquisitionProfile) -> dict:
    return {
        "schema_version": "target_profile_snapshot_v1",
        "profile_id": profile.id,
        "profile_key": profile.profile_key,
        "company_name": profile.company_name,
        "company_website": profile.company_website,
        "products": profile.products or [],
        "advantages": profile.advantages or [],
        "target_countries": profile.target_countries or [],
        "target_industries": profile.target_industries or [],
        "target_roles": profile.target_roles or [],
        "exclusions": profile.exclusions or [],
        "default_language": profile.default_language,
        "policy_version": profile.policy_version,
        "policy_json": profile.policy_json,
        "policy_snapshot_hash": profile.policy_snapshot_hash,
    }


def _validate_policy(value: Any) -> dict:
    if not isinstance(value, Mapping):
        raise SalesAutomationError("policy_json 必须是target_profile_policy_v1对象")
    policy = dict(value)
    if policy.get("schema_version") != "target_profile_policy_v1":
        raise SalesAutomationError("policy_json.schema_version 无效")
    required_sections = ("thresholds", "weights", "research_rules", "claim_rules")
    if any(not isinstance(policy.get(section), Mapping) for section in required_sections):
        raise SalesAutomationError(
            "policy_json 必须包含thresholds、weights、research_rules和claim_rules"
        )
    threshold = policy["thresholds"].get("research_threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 <= threshold <= 100:
        raise SalesAutomationError("research_threshold 必须在0至100之间")
    return _json_value(policy)


def get_profile(db: Session) -> AcquisitionProfile | None:
    return db.query(AcquisitionProfile).filter(
        AcquisitionProfile.profile_key == "default",
        AcquisitionProfile.deleted_at.is_(None),
    ).one_or_none()


def upsert_profile(db: Session, payload: Any, actor_id: int) -> AcquisitionProfile:
    data = _data(payload)
    policy = _validate_policy(data.get("policy_json"))
    policy_version = str(data.get("policy_version") or "").strip()
    if not policy_version:
        raise SalesAutomationError("policy_version 必填")
    profile = get_profile(db)
    if profile is None:
        profile = AcquisitionProfile(profile_key="default", created_by=actor_id)
        db.add(profile)
    elif profile.policy_version == policy_version:
        before = _canonical_json(_policy_snapshot(profile))
        proposed = dict(_policy_snapshot(profile))
        proposed.update({key: data[key] for key in data if key in proposed})
        proposed["policy_json"] = policy
        if before != _canonical_json(proposed):
            raise ConflictError("画像或策略变化必须使用新的 policy_version")
    for field in (
        "company_name",
        "company_website",
        "products",
        "advantages",
        "target_countries",
        "target_industries",
        "target_roles",
        "exclusions",
        "default_language",
    ):
        if field in data:
            setattr(profile, field, data[field])
    if not str(profile.company_name or "").strip():
        raise SalesAutomationError("company_name 必填")
    profile.policy_version = policy_version
    profile.policy_json = policy
    profile.policy_snapshot_hash = _hash({
        "profile": {
            field: getattr(profile, field)
            for field in (
                "company_name", "company_website", "products", "advantages",
                "target_countries", "target_industries", "target_roles",
                "exclusions", "default_language",
            )
        },
        "policy_version": policy_version,
        "policy_json": policy,
    })
    profile.policy_applied_at = beijing_now()
    profile.updated_by = actor_id
    db.commit()
    db.refresh(profile)
    return profile


def create_search_job(db: Session, payload: Any, actor_id: int) -> SearchJob:
    data = _data(payload)
    profile = get_profile(db)
    if profile is None:
        raise ConflictError("请先完善获客模型")
    name = str(data.get("name") or "").strip()
    if not name:
        raise SalesAutomationError("name 必填")
    target_count = int(data.get("target_count") or 0)
    if target_count <= 0:
        raise SalesAutomationError("target_count 必须大于0")
    criteria = _json_value(data.get("criteria_json") or {})
    adapter = str(data.get("adapter") or "agent")
    snapshot = _policy_snapshot(profile)
    snapshot_hash = _hash(snapshot)
    profile_id = profile.id
    policy_version = profile.policy_version
    idem = str(data.get("idempotency_key") or _hash({
        "name": name,
        "target_count": target_count,
        "adapter": adapter,
        "criteria": criteria,
        "profile_snapshot_hash": snapshot_hash,
    }))
    if len(idem) != 64:
        raise SalesAutomationError("idempotency_key 必须是64字符")
    existing = db.query(SearchJob).filter(SearchJob.idempotency_key == idem).one_or_none()
    if existing is not None:
        if not _search_job_matches_request(
            existing,
            profile_id=profile_id,
            policy_version=policy_version,
            name=name,
            target_count=target_count,
            adapter=adapter,
            criteria=criteria,
            snapshot_hash=snapshot_hash,
        ):
            raise ConflictError("idempotency_key已用于不同搜索任务材料")
        return existing
    job = SearchJob(
        profile_id=profile_id,
        name=name,
        status="pending",
        adapter=adapter,
        target_count=target_count,
        criteria_json=_json_value(criteria),
        profile_snapshot=snapshot,
        policy_version=policy_version,
        profile_snapshot_hash=snapshot_hash,
        idempotency_key=idem,
        ingestion_receipts={},
        result_count=0,
        created_customer_count=0,
        deduplicated_count=0,
        researched_count=0,
        qualified_count=0,
        provider_usage_json=[],
        cost_status="pending",
        attempt_count=0,
        created_by=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError as exc:
        # MySQL REPEATABLE READ keeps the pre-conflict read view until the
        # outer transaction ends.  End it before reading the unique winner.
        db.rollback()
        existing = db.query(SearchJob).filter(SearchJob.idempotency_key == idem).one_or_none()
        if existing is None:
            raise ConflictError("RETRY_NEW_TRANSACTION") from exc
        if not _search_job_matches_request(
            existing,
            profile_id=profile_id,
            policy_version=policy_version,
            name=name,
            target_count=target_count,
            adapter=adapter,
            criteria=criteria,
            snapshot_hash=snapshot_hash,
        ):
            raise ConflictError("idempotency_key已用于不同搜索任务材料")
        return existing
    db.commit()
    db.refresh(job)
    return job


def _search_job_matches_request(
    row: SearchJob,
    *,
    profile_id: int,
    policy_version: str,
    name: str,
    target_count: int,
    adapter: str,
    criteria: Mapping,
    snapshot_hash: str,
) -> bool:
    return (
        row.profile_id == profile_id
        and row.policy_version == policy_version
        and row.profile_snapshot_hash == snapshot_hash
        and row.name == name
        and row.target_count == target_count
        and row.adapter == adapter
        and _canonical_json(row.criteria_json or {}) == _canonical_json(criteria)
    )


def get_search_job(db: Session, job_id: int, *, for_update: bool = False) -> SearchJob:
    query = db.query(SearchJob).filter(SearchJob.id == job_id)
    if for_update:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise NotFoundError("搜索任务不存在")
    return row


def list_search_jobs(
    db: Session,
    page: int,
    page_size: int,
    status: str | None = None,
) -> tuple[list[SearchJob], int]:
    query = db.query(SearchJob)
    if status:
        query = query.filter(SearchJob.status == status)
    total = query.count()
    rows = query.order_by(SearchJob.created_at.desc(), SearchJob.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    return rows, total


def list_claimable_search_jobs(db: Session, page: int, page_size: int) -> tuple[list[SearchJob], int]:
    now = beijing_now()
    query = db.query(SearchJob).filter(or_(
        SearchJob.status == "pending",
        and_(SearchJob.status == "running", SearchJob.lease_expires_at <= now),
    ))
    total = query.count()
    return (
        query.order_by(SearchJob.created_at, SearchJob.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all(),
        total,
    )


def _claim_owner(actor_id: int, agent_id: str) -> str:
    cleaned = str(agent_id or "").strip()
    if not cleaned or len(cleaned) > 96:
        raise SalesAutomationError("agent_id 必填且不超过96字符")
    return f"{actor_id}:{cleaned}"


def claim_search_job(db: Session, job_id: int, actor_id: int, agent_id: str) -> tuple[SearchJob, str]:
    job = get_search_job(db, job_id, for_update=True)
    lease_now = beijing_now()
    reclaimable = (
        job.status == "running"
        and job.lease_expires_at is not None
        and job.lease_expires_at <= lease_now
    )
    if job.status != "pending" and not reclaimable:
        raise ConflictError("任务不是等待领取状态，或仍由其他Agent执行")
    token = secrets.token_urlsafe(32)
    job.status = "running"
    job.started_at = job.started_at or beijing_now()
    job.finished_at = None
    job.error_code = None
    job.error_message = None
    job.claimed_by = _claim_owner(actor_id, agent_id)
    job.lease_token_hash = _hash(token)
    job.lease_expires_at = lease_now + timedelta(minutes=LEASE_MINUTES)
    job.attempt_count += 1
    db.commit()
    db.refresh(job)
    return job, token


def _leased_job(
    db: Session,
    job_id: int,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> SearchJob:
    job = get_search_job(db, job_id, for_update=True)
    if job.claimed_by != _claim_owner(actor_id, agent_id):
        raise ConflictError("任务租约不属于当前Agent")
    if not lease_token or not secrets.compare_digest(job.lease_token_hash or "", _hash(lease_token)):
        raise ConflictError("任务租约无效")
    if job.lease_expires_at is None or job.lease_expires_at <= beijing_now():
        raise ConflictError("任务租约已过期，请重新领取")
    return job


def heartbeat_search_job(
    db: Session,
    job_id: int,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> SearchJob:
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以续租")
    job.lease_expires_at = beijing_now() + timedelta(minutes=LEASE_MINUTES)
    db.commit()
    db.refresh(job)
    return job


def requeue_search_job(db: Session, job_id: int, actor_id: int | None = None) -> SearchJob:
    job = get_search_job(db, job_id, for_update=True)
    if job.status != "failed":
        raise ConflictError("只有失败任务可以重新排队")
    job.status = "pending"
    job.error_code = None
    job.error_message = None
    job.finished_at = None
    job.claimed_by = None
    job.lease_token_hash = None
    job.lease_expires_at = None
    db.commit()
    db.refresh(job)
    return job


def complete_search_job(
    db: Session,
    job_id: int,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> SearchJob:
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以完成")
    job.status = "completed"
    job.finished_at = beijing_now()
    job.claimed_by = None
    job.lease_token_hash = None
    job.lease_expires_at = None
    db.commit()
    db.refresh(job)
    return job


def fail_search_job(
    db: Session,
    job_id: int,
    error_code: str,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> SearchJob:
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以标记失败")
    safe_message = agent_failure_message(error_code)
    job.status = "failed"
    job.error_code = str(error_code)
    job.error_message = safe_message
    job.finished_at = beijing_now()
    job.claimed_by = None
    job.lease_token_hash = None
    job.lease_expires_at = None
    db.commit()
    db.refresh(job)
    return job


def _research_threshold(job: SearchJob) -> Decimal:
    policy = job.profile_snapshot.get("policy_json", {}) if isinstance(job.profile_snapshot, dict) else {}
    thresholds = policy.get("thresholds", {}) if isinstance(policy, dict) else {}
    return _score(thresholds.get("research_threshold", 100))


def _ensure_search_research_task(
    db: Session,
    *,
    job: SearchJob,
    result: SearchResult,
    actor_id: int,
) -> tuple[CustomerResearchTask, bool]:
    logical_customer_id = db.query(logical_owner_expression(
        SearchResult, "search_result",
    )).filter(SearchResult.id == result.id).scalar()
    account_exists = db.query(CustomerAccount.id).filter(
        CustomerAccount.id == logical_customer_id,
        CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account_exists is None:
        raise NotFoundError("客户不存在")
    input_snapshot = {
        "schema_version": "research_input_v1",
        "search_result_id": result.id,
        "target_profile_id": job.profile_id,
        "profile_snapshot_hash": job.profile_snapshot_hash,
    }
    fingerprint = _hash({
        "customer_id": logical_customer_id,
        "task_type": "high_score_candidate",
        "source_ref_type": "search_result",
        "source_ref_id": str(result.id),
        "research_policy_version": job.policy_version,
        "input_snapshot": input_snapshot,
    })
    existing = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.task_fingerprint == fingerprint,
    ).one_or_none()
    if existing is not None:
        return existing, False
    active = db.query(CustomerResearchTask).filter(
        logical_root_predicate(
            CustomerResearchTask, "research_task", logical_customer_id,
        ),
        CustomerResearchTask.task_type == "high_score_candidate",
        CustomerResearchTask.research_policy_version == job.policy_version,
        or_(
            CustomerResearchTask.task_status.in_(("pending", "running")),
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
        customer_id=logical_customer_id,
        task_type="high_score_candidate",
        source_ref_type="search_result",
        source_ref_id=str(result.id),
        tier=None,
        task_status="pending",
        gate_status="pending",
        result_review_status="pending",
        selection_reason=[{
            "reason": "score_threshold_met",
            "best_score": format(Decimal(result.best_score), "f"),
            "search_result_id": result.id,
        }],
        research_policy_version=job.policy_version,
        task_fingerprint=fingerprint,
        input_snapshot=input_snapshot,
        result_schema_version=None,
        result_json=None,
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="search result score and public-business evidence",
        research_summary=None,
        evidence_fact_ids=[],
        lease_generation=0,
        attempt_count=0,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.query(CustomerResearchTask).filter(
            CustomerResearchTask.task_fingerprint == fingerprint,
        ).one_or_none()
        if existing is None:
            raise
        return existing, False
    return row, True


def _source_fingerprint(
    result_id: int,
    request_key: str,
    provider: str,
    content_hash: str,
    policy_version: str,
) -> str:
    return _hash({
        "schema_version": "search_result_source_v1",
        "result_id": result_id,
        "request_key": request_key,
        "source_provider": provider,
        "source_content_hash": content_hash,
        "score_policy_version": policy_version,
    })


def _result_for_customer(db: Session, job: SearchJob, customer_id: int) -> tuple[SearchResult, bool]:
    existing = db.query(SearchResult).filter(
        SearchResult.job_id == job.id,
        logical_root_predicate(SearchResult, "search_result", customer_id),
    ).with_for_update().one_or_none()
    if existing is not None:
        return existing, False
    candidate = SearchResult(
        job_id=job.id,
        customer_id=customer_id,
        best_rank=None,
        best_score=Decimal("0.00"),
        aggregated_score_reasons={"schema_version": "search_score_aggregate_v1", "sources": []},
        result_status="active",
    )
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate, True
    except IntegrityError:
        existing = db.query(SearchResult).filter(
            SearchResult.job_id == job.id,
            logical_root_predicate(SearchResult, "search_result", customer_id),
        ).with_for_update().one_or_none()
        if existing is None:
            raise
        return existing, False


def _refresh_result_aggregate(db: Session, result: SearchResult) -> None:
    sources = db.query(SearchResultSource).filter(
        SearchResultSource.result_id == result.id,
    ).order_by(SearchResultSource.id).all()
    ranks = [row.rank for row in sources if row.rank is not None]
    result.best_rank = min(ranks) if ranks else None
    result.best_score = max((Decimal(row.score) for row in sources), default=Decimal("0.00"))
    result.aggregated_score_reasons = {
        "schema_version": "search_score_aggregate_v1",
        "best_score": format(Decimal(result.best_score), "f"),
        "sources": [
            {
                "result_source_id": row.id,
                "source_provider": row.source_provider,
                "score": format(Decimal(row.score), "f"),
                "score_reasons": row.score_reasons or [],
                "source_record_id": row.source_record_id,
            }
            for row in sources
        ],
    }
    result.updated_at = beijing_now()
    db.flush()


def _resolve_candidate_context(
    db: Session,
    *,
    data: Mapping[str, Any],
    source_record,
    source_system: str,
    source_account_key: str,
    source_entity_type: str,
    external_context_id: str,
    actor_id: int,
    worker_id: str,
):
    identities: list[IdentityCandidate] = []
    website = data.get("website")
    if source_system == "okki":
        identities.append(IdentityCandidate(
            identifier_type="company_id",
            raw_value=external_context_id,
            verification_status="verified",
            confidence=Decimal("1.0000"),
            is_primary=True,
        ))
    elif source_system == "official_registry":
        identities.append(IdentityCandidate(
            identifier_type="business_id",
            raw_value=external_context_id,
            verification_status="verified",
            confidence=Decimal("1.0000"),
            is_primary=True,
        ))
    elif website:
        identities.append(IdentityCandidate(
            identifier_type="website_domain",
            raw_value=normalize_domain(str(website)),
            verification_status="candidate",
            confidence=Decimal("0.8000"),
            is_primary=True,
        ))
    return resolve_business_context(
        db,
        source_system=source_system,
        source_account_key=source_account_key,
        source_entity_type=source_entity_type,
        external_context_id=external_context_id,
        source_record_id=source_record.id,
        company_name=data.get("company_name"),
        contact_name=data.get("contact_name"),
        contact_email=data.get("contact_email"),
        identity_candidates=identities,
        created_by=actor_id,
        worker_id=worker_id,
    )


def ingest_candidates(
    db: Session,
    job_id: int,
    candidates: list[Any],
    request_key: str,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> dict:
    if not request_key or len(request_key) > 64:
        raise SalesAutomationError("request_key 必填且不超过64字符")
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以接收新候选")
    normalized_payload = [_json_value(_data(item)) for item in candidates]
    payload_hash = _hash(normalized_payload)
    receipts = dict(job.ingestion_receipts or {})
    previous = receipts.get(request_key)
    if previous is not None:
        if previous.get("payload_hash") != payload_hash:
            raise ConflictError("相同 request_key 的候选内容不一致")
        return previous["summary"]

    customer_ids: set[int] = set()
    result_ids: set[int] = set()
    task_ids: set[int] = set()
    created_customers = 0
    appended_sources = 0
    processed_candidates = 0
    quarantined_sources = 0
    for position, raw in enumerate(candidates, start=1):
        data = _data(raw)
        source_system = str(data.get("source_system") or "public_web").strip()
        source_account_key = str(data.get("source_account_key") or "global").strip()
        source_entity_type = str(data.get("source_entity_type") or "company_page").strip()
        external_record_id = str(data.get("external_record_id") or "").strip()
        external_context_id = str(data.get("external_context_id") or "").strip()
        provider = str(data.get("source_provider") or job.adapter).strip()
        if not all((source_system, source_account_key, source_entity_type, external_record_id, external_context_id, provider)):
            raise SalesAutomationError("候选的稳定信源和商业上下文标识必填")
        captured_at = _datetime(data.get("captured_at"), "captured_at")
        source_url = normalize_source_url(data["source_url"]) if data.get("source_url") else None
        score = _score(data.get("score"))
        reasons = _json_value(data.get("score_reasons") or [])
        payload = _json_value({
            key: value for key, value in data.items()
            if key not in {"agent_id", "lease_token"}
        })
        source_record = append_source_record(
            db,
            customer_id=None,
            source_system=source_system,
            source_account_key=source_account_key,
            source_entity_type=source_entity_type,
            external_record_id=external_record_id,
            payload_schema_version="search_candidate_v1",
            payload_json=payload,
            publisher_key=provider,
            source_family_key=external_context_id,
            source_url=source_url,
            occurred_at=captured_at,
            captured_at=captured_at,
            processing_status="pending",
        )
        try:
            context = _resolve_candidate_context(
                db,
                data=data,
                source_record=source_record,
                source_system=source_system,
                source_account_key=source_account_key,
                source_entity_type=source_entity_type,
                external_context_id=external_context_id,
                actor_id=actor_id,
                worker_id=f"search:{job.id}:{request_key}",
            )
        except CustomerTransactionRetryRequired as exc:
            db.rollback()
            raise ConflictError("RETRY_NEW_TRANSACTION") from exc
        except CustomerDomainError as exc:
            source_record.processing_status = "quarantined"
            if exc.error_code == "IDENTITY_RESOLUTION_CONFLICT":
                source_record.processing_error_code = "identity_resolution_conflict"
                source_record.processing_error_message = "候选商业身份与现有客户主体冲突；请人工核验"
            else:
                source_record.processing_error_code = "invalid_external_identity"
                source_record.processing_error_message = (
                    "候选商业身份无法安全解析；请核验官网或外部主体标识"
                )
            quarantined_sources += 1
            continue
        except InvalidExternalUrl:
            source_record.processing_status = "quarantined"
            source_record.processing_error_code = "invalid_external_identity"
            source_record.processing_error_message = (
                "候选商业身份无法安全解析；请核验官网或外部主体标识"
            )
            quarantined_sources += 1
            continue
        source_record.processing_status = "processed"
        processed_candidates += 1
        created_customers += int(context.created)
        customer_ids.add(context.customer.id)
        result, _created_result = _result_for_customer(db, job, context.customer.id)
        result_ids.add(result.id)
        fingerprint = _source_fingerprint(
            result.id,
            request_key,
            provider,
            source_record.content_hash,
            job.policy_version,
        )
        source = db.query(SearchResultSource).filter(
            SearchResultSource.source_fingerprint == fingerprint,
        ).one_or_none()
        if source is None:
            source = SearchResultSource(
                result_id=result.id,
                request_key=request_key,
                source_record_id=source_record.id,
                source_provider=provider,
                source_url=source_url,
                captured_at=captured_at,
                rank=int(data.get("rank") or position),
                score=score,
                score_reasons=reasons,
                allocated_cost_usd=Decimal(str(data.get("allocated_cost_usd") or 0)),
                source_fingerprint=fingerprint,
            )
            try:
                with db.begin_nested():
                    db.add(source)
                    db.flush()
                appended_sources += 1
            except IntegrityError:
                source = db.query(SearchResultSource).filter(
                    SearchResultSource.source_fingerprint == fingerprint,
                ).one()
        _refresh_result_aggregate(db, result)
        if result.best_score >= _research_threshold(job):
            task, _created_task = _ensure_search_research_task(
                db,
                job=job,
                result=result,
                actor_id=actor_id,
            )
            task_ids.add(task.id)

    job.result_count = db.query(SearchResult).filter(SearchResult.job_id == job.id).count()
    job.created_customer_count += created_customers
    job.deduplicated_count += max(0, processed_candidates - created_customers)
    search_result_ids = [
        str(row_id)
        for (row_id,) in db.query(SearchResult.id).filter(SearchResult.job_id == job.id).all()
    ]
    job.researched_count = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.source_ref_type == "search_result",
        CustomerResearchTask.source_ref_id.in_(search_result_ids),
    ).count() if job.result_count else 0
    summary = {
        "received": len(candidates),
        "unique_customers": len(customer_ids),
        "created_customers": created_customers,
        "appended_sources": appended_sources,
        "quarantined_sources": quarantined_sources,
        "result_ids": sorted(result_ids),
        "customer_ids": sorted(customer_ids),
        "research_task_ids": sorted(task_ids),
    }
    receipts[request_key] = {"payload_hash": payload_hash, "summary": summary}
    job.ingestion_receipts = receipts
    db.commit()
    return summary


def list_search_results(
    db: Session,
    job_id: int,
    page: int,
    page_size: int,
) -> tuple[list[SearchResult], int]:
    get_search_job(db, job_id)
    owner_id = logical_owner_expression(SearchResult, "search_result")
    query = db.query(
        SearchResult, owner_id.label("logical_customer_id"),
    ).filter(SearchResult.job_id == job_id)
    total = query.count()
    results = query.order_by(
        SearchResult.best_score.desc(),
        SearchResult.best_rank.asc(),
        SearchResult.id.asc(),
    ).offset((page - 1) * page_size).limit(page_size).all()
    rows = []
    for row, logical_customer_id in results:
        row.logical_customer_id = int(logical_customer_id)
        rows.append(row)
    return rows, total


__all__ = [
    "ConflictError",
    "NotFoundError",
    "SalesAutomationError",
    "claim_search_job",
    "complete_search_job",
    "create_search_job",
    "fail_search_job",
    "get_profile",
    "get_search_job",
    "heartbeat_search_job",
    "ingest_candidates",
    "list_claimable_search_jobs",
    "list_search_jobs",
    "list_search_results",
    "requeue_search_job",
    "upsert_profile",
]
