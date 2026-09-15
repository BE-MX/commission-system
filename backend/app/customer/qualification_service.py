"""Human qualification queue: one current research per customer and target scope."""

import hashlib
import json

from sqlalchemy import String, and_, case, cast, func, or_
from sqlalchemy.orm import aliased

from app.core.time import beijing_now, to_beijing_naive
from app.customer import evidence_service, query_service
from app.customer.access_service import CustomerAccessDenied
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.models import (
    CustomerAccount, CustomerFact, CustomerQualificationReview, CustomerResearchTask, SearchJob, SearchResult,
)
from app.customer.workbench_service import customer_labels
from app.customer.workflow_service import CustomerWorkflowConflict, CustomerWorkflowNotFound
from app.sales_automation import public_pool_service


def _ranked_research(db, user, customer_id=None):
    owner = logical_owner_expression(CustomerResearchTask, "research_task")
    scope_type = case((SearchJob.profile_id.isnot(None), "target_profile"), else_="source")
    scope_ref = case((SearchJob.profile_id.isnot(None), cast(SearchJob.profile_id, String)), else_="public_pool")
    result_ref = cast(SearchResult.id, String)
    if db.get_bind().dialect.name == "mysql":
        # CASE/CAST expressions inherit the MySQL 8 connection collation;
        # match the stored scope and source-reference columns at both joins.
        scope_type = scope_type.collate("utf8mb4_unicode_ci")
        scope_ref = scope_ref.collate("utf8mb4_unicode_ci")
        result_ref = result_ref.collate("utf8mb4_unicode_ci")
    query = query_service.scoped_research_query(db, user)
    if customer_id is not None:
        query = query.filter(owner == customer_id)
    return query.outerjoin(
        SearchResult, and_(CustomerResearchTask.source_ref_type == "search_result",
                           CustomerResearchTask.source_ref_id == result_ref,
                           logical_owner_expression(SearchResult, "search_result") == owner),
    ).outerjoin(SearchJob, SearchJob.id == SearchResult.job_id).filter(
        CustomerResearchTask.task_status == "completed",
        CustomerResearchTask.gate_status == "passed",
        CustomerResearchTask.result_review_status == "accepted",
        or_(CustomerResearchTask.source_ref_type.is_(None),
            CustomerResearchTask.source_ref_type != "search_result", SearchJob.id.isnot(None)),
    ).with_entities(
        CustomerResearchTask.id.label("task_id"), owner.label("customer_id"),
        scope_type.label("scope_type"), scope_ref.label("scope_ref_id"),
        SearchJob.name.label("target_name"), SearchResult.best_score.label("match_score"),
        func.row_number().over(partition_by=(owner, scope_type, scope_ref), order_by=(
            CustomerResearchTask.updated_at.desc(), CustomerResearchTask.id.desc(),
        )).label("rank"),
    ).subquery()


def _queue_query(db, user, customer_id=None):
    ranked = _ranked_research(db, user, customer_id)
    current = CustomerQualificationReview
    global_review = aliased(CustomerQualificationReview)
    now = beijing_now()
    global_blocks = db.query(global_review.id).filter(
        global_review.customer_id == ranked.c.customer_id,
        global_review.is_current.is_(True), global_review.scope_type == "global",
        or_(global_review.decision != "deferred", global_review.review_after.is_(None), global_review.review_after > now),
    ).exists()
    query = db.query(CustomerResearchTask, ranked.c.customer_id, ranked.c.scope_type,
        ranked.c.scope_ref_id, ranked.c.target_name, ranked.c.match_score,
        current.id.label("current_review_id"), current.reason_text.label("previous_reason"),
    ).join(ranked, ranked.c.task_id == CustomerResearchTask.id).outerjoin(
        current, and_(current.customer_id == ranked.c.customer_id, current.is_current.is_(True),
                      current.scope_type == ranked.c.scope_type, current.scope_ref_id == ranked.c.scope_ref_id),
    ).filter(ranked.c.rank == 1)
    pending = and_(~global_blocks, or_(current.id.is_(None), and_(
        current.decision == "deferred", current.review_after <= now,
    )))
    return query, pending


def list_queue(db, user, *, page=1, page_size=20, keyword=None):
    query, pending = _queue_query(db, user)
    query = query.filter(pending)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.join(CustomerAccount, CustomerAccount.id == logical_owner_expression(CustomerResearchTask, "research_task")).filter(
            or_(CustomerAccount.display_name.ilike(pattern), CustomerAccount.customer_code.ilike(pattern)),
        )
    total = query.count()
    rows = query.order_by(CustomerResearchTask.updated_at.desc(), CustomerResearchTask.id.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()
    accesses = query_service._batch_research_access(db, user, {int(row.customer_id) for row in rows})
    labels = customer_labels(db, {int(row.customer_id) for row in rows})
    items = []
    for row in rows:
        task = row[0]
        item = query_service.serialize_research_task(task, accesses[int(row.customer_id)], customer_id=int(row.customer_id))
        item.update(labels.get(int(row.customer_id), {}))
        item.update({"scope_type": row.scope_type, "scope_ref_id": row.scope_ref_id,
                     "scope_label": row.target_name or "公海开发",
                     "match_score": float(row.match_score) if row.match_score is not None else None,
                     "current_review_id": row.current_review_id,
                     "can_review": accesses[int(row.customer_id)].scope_kind != "public_pool"})
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def get_context(db, user, task_id, *, customer_id=None):
    query, pending = _queue_query(db, user, customer_id)
    row = query.filter(CustomerResearchTask.id == task_id).one_or_none()
    if row is None:
        raise CustomerWorkflowNotFound("QUALIFICATION_RESEARCH_NOT_AVAILABLE")
    task = row[0]
    access = query_service._access(db, int(row.customer_id), user, read_permissions=query_service.RESEARCH_READ)
    detail = query_service.serialize_research_task(task, access, include_content=True, customer_id=int(row.customer_id))
    detail.update(customer_labels(db, [access.customer_id]).get(access.customer_id, {}))
    if access.scope_kind == "public_pool":
        return {**detail, "can_review": False, "blocked_reason": "公海资料已脱敏，请联系有权限的负责人复核。"}
    facts = evidence_service.visible_facts(db, access).filter(CustomerFact.id.in_(task.evidence_fact_ids or [])).all()
    evidence = evidence_service.serialize_facts(db, facts)
    usable = {item["id"] for item in evidence if item["selectable"]}
    account = db.get(CustomerAccount, access.customer_id)
    snapshot = {
        "schema_version": "qualification_snapshot_v1", "customer_id": access.customer_id,
        "profile_version_id": account.current_profile_version_id,
        "research_task_id": task.id, "research_fingerprint": task.task_fingerprint,
        "research_updated_at": query_service.iso_beijing(task.updated_at),
        "result_hash": _hash(task.result_json), "evidence_fact_ids": sorted(usable),
        "evidence_versions": sorted((fact.id, fact.fact_fingerprint) for fact in facts),
        "scope_type": row.scope_type, "scope_ref_id": row.scope_ref_id,
        "match_score": float(row.match_score) if row.match_score is not None else None,
    }
    is_pending = query.filter(CustomerResearchTask.id == task_id, pending).first() is not None
    reason = None
    if not is_pending:
        reason = "该范围已有有效审核结论，请刷新待审核列表。"
    elif account.current_profile_version_id is None:
        reason = "客户档案尚未就绪，请先完成档案整理。"
    elif usable != set(task.evidence_fact_ids or []):
        reason = "部分证据已过期或不可见，请先重新复核研究结果。"
    detail.update({"evidence": evidence, "scope_type": row.scope_type, "scope_ref_id": row.scope_ref_id,
        "scope_label": row.target_name or "公海开发", "match_score": snapshot["match_score"],
        "current_review_id": row.current_review_id, "previous_reason": row.previous_reason,
        "context_hash": _hash(snapshot), "review_snapshot": snapshot,
        "can_review": reason is None, "blocked_reason": reason})
    return detail


def submit_decision(db, user, task_id, payload):
    # The caller can only select a business decision; provenance comes from Ark.
    # Match public_pool_service's research -> account lock order. Refresh before
    # computing the context, including identities already loaded by authorization.
    task = query_service.scoped_research_query(db, user).filter(
        CustomerResearchTask.id == task_id,
    ).populate_existing().with_for_update().one_or_none()
    if task is None:
        raise CustomerWorkflowNotFound("QUALIFICATION_RESEARCH_NOT_AVAILABLE")
    owner = db.query(logical_owner_expression(CustomerResearchTask, "research_task")).filter(
        CustomerResearchTask.id == task_id,
    ).scalar()
    db.query(CustomerAccount).filter(CustomerAccount.id == owner).populate_existing().with_for_update().one()
    db.query(CustomerFact).filter(CustomerFact.id.in_(task.evidence_fact_ids or [])).populate_existing().with_for_update().all()
    access = query_service._access(db, int(owner), user, read_permissions=query_service.RESEARCH_READ)
    if access.scope_kind == "public_pool":
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")
    submitted = payload.model_dump(mode="json")
    submission_hash = _hash({"actor": int(user["sub"]), "task_id": task_id, **submitted})
    replay = db.query(CustomerQualificationReview).filter(
        CustomerQualificationReview.customer_id == int(owner),
        CustomerQualificationReview.review_snapshot["submission_hash"].as_string() == submission_hash,
    ).one_or_none()
    if replay is not None:
        return {"qualification_review_id": replay.id, "decision": replay.decision, "replayed": True}
    detail = get_context(db, user, task_id, customer_id=int(owner))
    if not detail["can_review"] or detail["context_hash"] != payload.context_hash:
        raise CustomerWorkflowConflict("QUALIFICATION_CONTEXT_CHANGED")
    if detail["current_review_id"] != payload.expected_current_review_id:
        raise CustomerWorkflowConflict("QUALIFICATION_REVIEW_CHANGED")
    decision, reason = {
        "approve": ("approved", "qualified"), "defer": ("deferred", "not_now"),
        "supplement": ("deferred", "bad_data"), "reject": ("rejected", "poor_fit"),
    }[payload.decision]
    snapshot = {**detail["review_snapshot"], "submission_hash": submission_hash,
                "priority_level": "C"}
    score = detail.get("match_score")
    if score is not None:
        # Do not invent thresholds: queue priority stays unranked without a policy-derived grade.
        snapshot["match_score"] = score
    result = public_pool_service.submit_qualification_review(
        db, customer_id=detail["customer_id"], review_source="public_pool_research", source_ref_id=str(task_id),
        decision=decision, reason_code=reason, reason_text=payload.reason,
        scope_type=detail["scope_type"], scope_ref_id=detail["scope_ref_id"],
        policy_version=detail["research_policy_version"], review_snapshot=snapshot,
        decision_request_key=payload.request_key, expected_current_review_id=payload.expected_current_review_id,
        reviewed_by=int(user["sub"]), review_after=to_beijing_naive(payload.review_after),
    )
    return {"qualification_review_id": result.id, "decision": result.decision, "replayed": False}
