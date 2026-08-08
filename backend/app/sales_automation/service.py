"""智能获客领域服务：确定性身份、幂等入库和证据约束。"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.sales_automation.models import (
    AcquisitionProfile,
    LeadCompany,
    SearchJob,
    SearchResult,
)
from app.sales_automation.identity import normalize_domain, normalize_source_url


class SalesAutomationError(ValueError):
    pass


class NotFoundError(SalesAutomationError):
    pass


class ConflictError(SalesAutomationError):
    pass


LEASE_MINUTES = 15


def _data(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    return dict(value)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError as exc:
            raise SalesAutomationError(f"{field} 格式无效") from exc
    raise SalesAutomationError(f"{field} 必填")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def get_profile(db: Session) -> AcquisitionProfile | None:
    return db.query(AcquisitionProfile).filter(
        AcquisitionProfile.profile_key == "default",
        AcquisitionProfile.deleted_at.is_(None),
    ).first()


def upsert_profile(db: Session, payload: Any, actor_id: int) -> AcquisitionProfile:
    data = _data(payload)
    profile = get_profile(db)
    if profile is None:
        profile = AcquisitionProfile(profile_key="default", created_by=actor_id)
        db.add(profile)
    for field in (
        "company_name", "company_website", "products", "advantages",
        "target_countries", "target_industries", "target_roles", "exclusions",
        "default_language",
    ):
        if field in data:
            setattr(profile, field, data[field])
    if not profile.company_name:
        raise SalesAutomationError("company_name 必填")
    profile.updated_by = actor_id
    db.commit()
    db.refresh(profile)
    return profile


def _profile_snapshot(profile: AcquisitionProfile) -> dict:
    return {
        "company_name": profile.company_name,
        "company_website": profile.company_website,
        "products": profile.products or [],
        "advantages": profile.advantages or [],
        "target_countries": profile.target_countries or [],
        "target_industries": profile.target_industries or [],
        "target_roles": profile.target_roles or [],
        "exclusions": profile.exclusions or [],
        "default_language": profile.default_language,
    }


def create_search_job(db: Session, payload: Any, actor_id: int) -> SearchJob:
    data = _data(payload)
    profile = get_profile(db)
    if profile is None:
        raise ConflictError("请先完善获客模型")
    idem = data.get("idempotency_key")
    if idem:
        existing = db.query(SearchJob).filter(SearchJob.idempotency_key == idem).first()
        if existing:
            return existing
    criteria = {
        "keywords": data.get("keywords") or [],
        "countries": data.get("countries") or [],
        "industries": data.get("industries") or [],
    }
    job = SearchJob(
        profile_id=profile.id,
        name=(data.get("name") or "").strip(),
        adapter=data.get("adapter") or "agent",
        target_count=int(data.get("target_count") or 20),
        criteria=criteria,
        profile_snapshot=_profile_snapshot(profile),
        idempotency_key=idem,
        ingestion_receipts={},
        created_by=actor_id,
        updated_by=actor_id,
    )
    if not job.name:
        raise SalesAutomationError("name 必填")
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idem:
            existing = db.query(SearchJob).filter(SearchJob.idempotency_key == idem).first()
            if existing:
                return existing
        raise
    db.refresh(job)
    return job


def get_search_job(db: Session, job_id: int, *, for_update: bool = False) -> SearchJob:
    query = db.query(SearchJob).filter(SearchJob.id == job_id, SearchJob.deleted_at.is_(None))
    if for_update:
        query = query.with_for_update()
    job = query.first()
    if job is None:
        raise NotFoundError("搜索任务不存在")
    return job


def list_search_jobs(db: Session, page: int, page_size: int, status: str | None = None) -> tuple[list[SearchJob], int]:
    query = db.query(SearchJob).filter(SearchJob.deleted_at.is_(None))
    if status:
        query = query.filter(SearchJob.status == status)
    total = query.count()
    rows = query.order_by(SearchJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def list_claimable_search_jobs(db: Session, page: int, page_size: int) -> tuple[list[SearchJob], int]:
    now = _now()
    query = db.query(SearchJob).filter(
        SearchJob.deleted_at.is_(None),
        or_(
            SearchJob.status == "pending",
            and_(SearchJob.status == "running", SearchJob.lease_expires_at <= now),
        ),
    )
    total = query.count()
    rows = query.order_by(SearchJob.created_at.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def _claim_owner(actor_id: int, agent_id: str) -> str:
    cleaned = (agent_id or "").strip()
    if not cleaned or len(cleaned) > 96:
        raise SalesAutomationError("agent_id 必填且不超过96字符")
    return f"{actor_id}:{cleaned}"


def claim_search_job(db: Session, job_id: int, actor_id: int, agent_id: str) -> tuple[SearchJob, str]:
    job = get_search_job(db, job_id, for_update=True)
    now = _now()
    reclaimable = job.status == "running" and job.lease_expires_at is not None and job.lease_expires_at <= now
    if job.status != "pending" and not reclaimable:
        raise ConflictError("任务不是等待领取状态，或仍由其他Agent执行")
    lease_token = secrets.token_urlsafe(32)
    job.status = "running"
    job.started_at = job.started_at or now
    job.finished_at = None
    job.error_code = None
    job.error_message = None
    job.claimed_by = _claim_owner(actor_id, agent_id)
    job.lease_token_hash = _hash(lease_token)
    job.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
    job.attempt_count += 1
    job.updated_by = actor_id
    db.commit()
    db.refresh(job)
    return job, lease_token


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
    if job.lease_expires_at is None or job.lease_expires_at <= _now():
        raise ConflictError("任务租约已过期，请重新领取")
    return job


def heartbeat_search_job(db: Session, job_id: int, actor_id: int, agent_id: str, lease_token: str) -> SearchJob:
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以续租")
    job.lease_expires_at = _now() + timedelta(minutes=LEASE_MINUTES)
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
    job.updated_by = actor_id
    db.commit()
    db.refresh(job)
    return job


def complete_search_job(db: Session, job_id: int, actor_id: int, agent_id: str, lease_token: str) -> SearchJob:
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以完成")
    job.status = "completed"
    job.finished_at = _now()
    job.updated_by = actor_id
    db.commit()
    db.refresh(job)
    return job


def fail_search_job(
    db: Session,
    job_id: int,
    error_message: str,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> SearchJob:
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以标记失败")
    job.status = "failed"
    job.error_code = "agent_failed"
    job.error_message = error_message[:2000]
    job.finished_at = _now()
    job.updated_by = actor_id
    db.commit()
    db.refresh(job)
    return job


def _score(profile: AcquisitionProfile, candidate: dict) -> tuple[float, list[str]]:
    haystack = " ".join(str(candidate.get(k) or "") for k in ("name", "industry", "description")).lower()
    reasons: list[str] = []
    score = 15.0
    country = (candidate.get("country") or "").strip().lower()
    for target in profile.target_countries or []:
        if target.strip().lower() == country:
            score += 25
            reasons.append(target)
            break
    for target in profile.target_industries or []:
        if target.strip().lower() in haystack:
            score += 35
            reasons.append(target)
            break
    product_matches = [p for p in (profile.products or []) if p.strip().lower() in haystack]
    if product_matches:
        score += min(20, 10 * len(product_matches))
        reasons.extend(product_matches[:2])
    for exclusion in profile.exclusions or []:
        if exclusion.strip().lower() in haystack:
            score -= 60
            reasons.append(f"排除：{exclusion}")
    return max(0, min(100, score)), reasons


def ingest_candidates(
    db: Session,
    job_id: int,
    candidates: list[Any],
    request_key: str,
    actor_id: int,
    agent_id: str,
    lease_token: str,
) -> dict:
    if not request_key:
        raise SalesAutomationError("request_key 必填")
    job = _leased_job(db, job_id, actor_id, agent_id, lease_token)
    receipts = dict(job.ingestion_receipts or {})
    payload_snapshot = _json_safe([_data(item) for item in candidates])
    payload_hash = _hash(json.dumps(payload_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if request_key in receipts:
        receipt = receipts[request_key]
        if receipt.get("payload_hash") != payload_hash:
            raise ConflictError("相同 request_key 的候选内容不一致")
        return receipt["summary"]
    if job.status != "running":
        raise ConflictError("只有执行中的任务可以接收新候选")
    profile = db.query(AcquisitionProfile).filter(AcquisitionProfile.id == job.profile_id).first()
    if profile is None:
        raise ConflictError("搜索任务引用的获客模型不存在")

    summary = {"received": len(candidates), "created": 0, "updated": 0, "deduplicated": 0}
    for rank, raw in enumerate(candidates, start=1):
        data = _data(raw)
        domain = normalize_domain(data.get("website"))
        source_url = normalize_source_url(data.get("source_url"))
        captured_at = _datetime(data.get("captured_at"), "captured_at")
        score, reasons = _score(profile, data)
        company = db.query(LeadCompany).filter(LeadCompany.normalized_domain == domain).first()
        was_created = company is None
        if company is None:
            candidate_company = LeadCompany(
                normalized_domain=domain,
                name=data["name"].strip(),
                website=f"https://{domain}",
                country=data.get("country"),
                industry=data.get("industry"),
                description=data.get("description"),
                match_score=score,
                score_reasons=reasons,
                created_by=job.created_by,
                updated_by=job.created_by,
            )
            try:
                with db.begin_nested():
                    db.add(candidate_company)
                    db.flush()
                company = candidate_company
                summary["created"] += 1
            except IntegrityError:
                company = db.query(LeadCompany).filter(LeadCompany.normalized_domain == domain).first()
                if company is None:
                    raise
                was_created = False
        else:
            company.name = data.get("name") or company.name
            company.country = data.get("country") or company.country
            company.industry = data.get("industry") or company.industry
            company.description = data.get("description") or company.description
            if score >= company.match_score:
                company.match_score = score
                company.score_reasons = reasons
            company.updated_by = job.created_by

        existing_result = db.query(SearchResult).filter(
            SearchResult.job_id == job.id,
            SearchResult.company_id == company.id,
        ).first()
        if existing_result:
            existing_result.request_key = request_key
            existing_result.source_provider = data.get("source_provider") or job.adapter
            existing_result.source_url = source_url
            existing_result.captured_at = captured_at
            existing_result.raw_payload = _json_safe(data)
            existing_result.rank = rank
            existing_result.score = score
            summary["deduplicated"] += 1
            continue
        result = SearchResult(
            job_id=job.id,
            company_id=company.id,
            request_key=request_key,
            source_provider=data.get("source_provider") or job.adapter,
            source_url=source_url,
            captured_at=captured_at,
            raw_payload=_json_safe(data),
            rank=rank,
            score=score,
            created_by=job.created_by,
            updated_by=job.created_by,
        )
        db.add(result)
        db.flush()
        if not was_created:
            summary["updated"] += 1

    job.result_count += summary["received"]
    job.created_count += summary["created"]
    job.deduplicated_count += summary["deduplicated"]
    receipts[request_key] = {"payload_hash": payload_hash, "summary": summary}
    job.ingestion_receipts = receipts
    db.commit()
    return summary


def list_leads(
    db: Session,
    page: int,
    page_size: int,
    status: str | None = None,
    keyword: str | None = None,
) -> tuple[list[LeadCompany], int]:
    query = db.query(LeadCompany).filter(LeadCompany.deleted_at.is_(None))
    if status:
        query = query.filter(LeadCompany.status == status)
    if keyword:
        query = query.filter(LeadCompany.name.ilike(f"%{keyword.strip()}%"))
    total = query.count()
    rows = query.order_by(LeadCompany.match_score.desc(), LeadCompany.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def get_lead(db: Session, company_id: int, *, for_update: bool = False) -> LeadCompany:
    query = db.query(LeadCompany).filter(LeadCompany.id == company_id, LeadCompany.deleted_at.is_(None))
    if for_update:
        query = query.with_for_update()
    company = query.first()
    if company is None:
        raise NotFoundError("候选公司不存在")
    return company


def approve_lead(db: Session, company_id: int, actor_id: int) -> LeadCompany:
    company = get_lead(db, company_id)
    company.status = "approved"
    company.owner_user_id = actor_id
    company.approved_at = _now()
    company.updated_by = actor_id
    db.commit()
    db.refresh(company)
    return company
