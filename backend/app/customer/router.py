"""Thin human-facing routes for unified customer operations."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.customer import proposal_service, query_service
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.models import CustomerAction, CustomerChangeProposal, CustomerOpportunity, CustomerResearchTask
from app.customer.schemas import ActionUpdate, OpportunityUpdate, ProposalCreate, ProposalDecision, ProposalExecute
from app.customer.workflow_service import CustomerWorkflowConflict, CustomerWorkflowError, CustomerWorkflowNotFound
from app.sales_automation import router as acquisition_views
from app.sales_automation import public_pool_service
from app.sales_automation.schemas import (
    ProfileUpsert, PublicPoolBatchCreate, QualificationReviewSubmit,
    ResearchResultReview, SearchJobCreate,
)


router = APIRouter()
CUSTOMER_READ = ("customer:read", "customer:read_all")
RESEARCH_READ = ("sales_automation:read", "customer:read_all")
OPPORTUNITY_READ = ("customer_opportunity:read", "customer:read_all")
ACTION_READ = ("customer_radar:read", "customer:read_all")
OPPORTUNITY_WRITE = ("customer_opportunity:write", "customer:admin")
ACTION_WRITE = ("customer_radar:write", "customer:admin")
PROPOSAL_ADMIN = ("customer:admin", "customer:read_all")
ACQUISITION_READ = ("sales_automation:read", "sales_automation:write", "sales_automation:admin")
ACQUISITION_WRITE = ("sales_automation:write", "sales_automation:admin")


def _user_id(user: dict) -> int:
    try:
        value = int(user["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误") from None
    return value


def _not_found():
    raise HTTPException(status.HTTP_404_NOT_FOUND, "CUSTOMER_NOT_FOUND_OR_FORBIDDEN")


def _access(
    db: Session, customer_id: int, user: dict, *,
    action_permissions=CUSTOMER_READ, allow_public_pool=True,
):
    try:
        return require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions=set(action_permissions),
            manage_permissions={"customer:admin"},
            allow_public_pool=allow_public_pool,
        )
    except CustomerAccessDenied:
        _not_found()


def _service_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (proposal_service.ProposalNotFound, CustomerWorkflowNotFound):
        _not_found()
    except (proposal_service.ProposalConflict, CustomerWorkflowConflict) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (proposal_service.ProposalError, CustomerWorkflowError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/customers")
def customers(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=255), db: Session = Depends(get_db),
    user=Depends(require_any_permission(*CUSTOMER_READ)),
):
    try:
        items, total = query_service.list_customers(db, user, page=page, page_size=page_size, keyword=keyword)
    except CustomerAccessDenied:
        _not_found()
    return ok(page_result(items, total, page, page_size))


@router.get("/customers/{customer_id}")
def customer_detail(
    customer_id: int, db: Session = Depends(get_db),
    user=Depends(require_any_permission(*CUSTOMER_READ)),
):
    try:
        return ok(query_service.get_customer(db, user, customer_id))
    except (CustomerAccessDenied, LookupError):
        _not_found()


@router.get("/customers/{customer_id}/timeline")
def customer_timeline(
    customer_id: int, page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
    user=Depends(require_any_permission(*CUSTOMER_READ)),
):
    try:
        items, total = query_service.list_timeline(db, user, customer_id, page=page, page_size=page_size)
    except CustomerAccessDenied:
        _not_found()
    return ok(page_result(items, total, page, page_size))


@router.get("/research-tasks")
def research_tasks(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*RESEARCH_READ)),
):
    try:
        items, total = query_service.list_research_tasks(db, user, page=page, page_size=page_size)
    except CustomerAccessDenied:
        _not_found()
    return ok(page_result(items, total, page, page_size))


@router.get("/acquisition-profile")
def acquisition_profile(db: Session = Depends(get_db), user=Depends(require_any_permission(*ACQUISITION_READ))):
    return acquisition_views.get_profile(db=db, _user=user)


@router.put("/acquisition-profile")
def save_acquisition_profile(payload: ProfileUpsert, db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    return acquisition_views.save_profile(payload, db=db, user=user)


@router.get("/search-jobs")
def search_jobs(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"), db: Session = Depends(get_db),
    user=Depends(require_any_permission(*ACQUISITION_READ)),
):
    return acquisition_views.list_search_jobs(page, page_size, status_filter, db, user)


@router.post("/search-jobs", status_code=status.HTTP_201_CREATED)
def create_search_job(payload: SearchJobCreate, db: Session = Depends(get_db), user=Depends(require_any_permission(*ACQUISITION_WRITE))):
    return acquisition_views.create_search_job(payload, db, user)


@router.post("/search-jobs/{job_id}/requeue")
def requeue_search_job(job_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission(*ACQUISITION_WRITE))):
    return acquisition_views.requeue_search_job(job_id, db, user)


@router.get("/search-jobs/{job_id}/results")
def search_job_results(
    job_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*ACQUISITION_READ)),
):
    return acquisition_views.list_search_results(job_id, page, page_size, db, user)


@router.get("/public-pool/audit")
def public_pool_audit(db: Session = Depends(get_db), user=Depends(require_any_permission(*ACQUISITION_READ))):
    return acquisition_views.get_public_pool_audit(db, user)


@router.post("/public-pool/audit/refresh")
def refresh_public_pool_audit(db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    return acquisition_views.refresh_public_pool_audit(db, user)


@router.get("/public-pool/batches")
def public_pool_batches(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*ACQUISITION_READ)),
):
    return acquisition_views.list_public_pool_batches(page, page_size, db, user)


@router.post("/public-pool/batches", status_code=status.HTTP_201_CREATED)
def create_public_pool_batch(payload: PublicPoolBatchCreate, db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    return acquisition_views.create_public_pool_batch(payload, db, user)


@router.get("/research-tasks/{task_id}")
def research_task_detail(task_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission(*RESEARCH_READ))):
    try:
        data = query_service.get_research_task(db, user, task_id)
    except (CustomerAccessDenied, LookupError):
        _not_found()
    return ok(data)


@router.post("/research-tasks/{task_id}/result-review")
def review_research_task(task_id: int, payload: ResearchResultReview, db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    row = db.query(CustomerResearchTask).filter(
        CustomerResearchTask.id == task_id,
        CustomerResearchTask.customer_id.in_(query_service._scoped_ids(
            db, user, read_permissions=query_service.RESEARCH_READ,
        )),
    ).one_or_none()
    if row is None:
        _not_found()
    _access(db, row.customer_id, user, action_permissions=RESEARCH_READ)
    return acquisition_views.review_research_result(task_id, payload, db, user)


@router.get("/qualification-queue")
def qualification_queue(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*RESEARCH_READ)),
):
    query = query_service.scoped_research_query(db, user).filter(
        CustomerResearchTask.task_status == "completed",
        CustomerResearchTask.result_review_status == "accepted",
    )
    total = query.count()
    rows = query.order_by(CustomerResearchTask.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok(page_result([
        query_service.serialize_research_task(
            row,
            _access(db, row.customer_id, user, action_permissions=RESEARCH_READ),
        )
        for row in rows
    ], total, page, page_size))


@router.post("/qualification-reviews", status_code=status.HTTP_201_CREATED)
def submit_qualification_review(payload: QualificationReviewSubmit, db: Session = Depends(get_db), user=Depends(require_any_permission(*ACQUISITION_WRITE))):
    access = _access(
        db, payload.customer_id, user,
        action_permissions=ACQUISITION_WRITE, allow_public_pool=True,
    )
    row = acquisition_views._call(
        public_pool_service.submit_qualification_review,
        db, **payload.model_dump(), reviewed_by=_user_id(user),
    )
    if access.scope_kind == "public_pool":
        return ok({
            "qualification_review_id": row.id,
            "customer_id": row.customer_id,
            "review_version": row.review_version,
            "decision": row.decision,
            "reason_code": row.reason_code,
            "is_current": row.is_current,
            "policy_version": row.policy_version,
            "reviewed_at": query_service.iso_beijing(row.reviewed_at),
        })
    return ok(acquisition_views._qualification(row))


@router.get("/opportunities")
def opportunities(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*OPPORTUNITY_READ)),
):
    try:
        items, total = query_service.list_opportunities(db, user, page=page, page_size=page_size)
    except CustomerAccessDenied:
        _not_found()
    return ok(page_result(items, total, page, page_size))


@router.put("/opportunities/{opportunity_id}")
def update_opportunity(
    opportunity_id: int, payload: OpportunityUpdate, db: Session = Depends(get_db),
    user=Depends(require_any_permission("customer_opportunity:write", "customer:admin")),
):
    scoped = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.id == opportunity_id,
        CustomerOpportunity.customer_id.in_(query_service._scoped_ids(
            db, user, read_permissions=OPPORTUNITY_WRITE,
            include_public_pool=False,
        )),
    ).one_or_none()
    if scoped is None:
        _not_found()
    access = _access(db, scoped.customer_id, user, action_permissions=OPPORTUNITY_WRITE, allow_public_pool=False)
    from app.insight.customer_opportunity_service import update_opportunity_status
    row = _service_call(
        update_opportunity_status, db, opportunity_id, payload.status, payload.reason,
        _user_id(user), evidence_event_ids=tuple(payload.evidence_event_ids),
        evidence_fact_ids=tuple(payload.evidence_fact_ids), linked_order_id=payload.linked_order_id,
        close_reason_code=payload.close_reason_code, close_reason_text=payload.close_reason_text,
        can_manage=access.can_manage,
    )
    return ok(query_service.serialize_opportunity(row))


@router.get("/actions")
def actions(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*ACTION_READ)),
):
    try:
        items, total = query_service.list_actions(db, user, page=page, page_size=page_size)
    except CustomerAccessDenied:
        _not_found()
    return ok(page_result(items, total, page, page_size))


@router.put("/actions/{action_id}")
def update_action(
    action_id: int, payload: ActionUpdate, db: Session = Depends(get_db),
    user=Depends(require_any_permission("customer_radar:write", "customer:admin")),
):
    scoped = db.query(CustomerAction).filter(
        CustomerAction.id == action_id,
        CustomerAction.customer_id.in_(query_service._scoped_ids(
            db, user, read_permissions=ACTION_WRITE,
            include_public_pool=False,
        )),
    ).one_or_none()
    if scoped is None:
        _not_found()
    access = _access(db, scoped.customer_id, user, action_permissions=ACTION_WRITE, allow_public_pool=False)
    from app.insight import customer_radar_service as service
    uid = _user_id(user)
    if payload.operation == "complete":
        row = _service_call(
            service.complete_action, db, action_id, uid, payload.feedback, payload.note,
            outcome_code=payload.outcome_code or "other", channel=payload.channel,
            occurred_at=payload.occurred_at, summary=payload.summary, next_step=payload.next_step,
            can_manage=access.can_manage,
        )
    elif payload.operation == "dismiss":
        row = _service_call(service.dismiss_action, db, action_id, uid, reason_code=payload.reason_code or "user_dismissed", note=payload.note, can_manage=access.can_manage)
    elif payload.operation == "snooze":
        if payload.snoozed_until is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "snoozed_until必填")
        row = _service_call(service.snooze_action, db, action_id, uid, payload.snoozed_until, can_manage=access.can_manage)
    else:
        row = _service_call(service.submit_feedback, db, action_id, payload.feedback or "", payload.note, uid, can_manage=access.can_manage)
    return ok(query_service.serialize_action(row))


def _proposal_sensitive_visible(row, accesses) -> bool:
    return bool(accesses) and all(
        row.data_classification in access.allowed_classifications()
        and row.visibility_scope in access.allowed_visibility_scopes()
        for access in accesses
    )


def _proposal_view(row, accesses=()):
    data = proposal_service.serialize_proposal(row)
    can_view_sensitive = _proposal_sensitive_visible(row, accesses)
    if not can_view_sensitive:
        data["payload_json"] = None
        data["evidence_fact_ids"] = []
        data["action_hash"] = None
    for field in ("expires_at", "created_at", "updated_at"):
        data[field] = query_service.iso_beijing(data[field])
    return data


def _proposal_scope_query(db, user):
    source_ids = query_service._scoped_ids(
        db, user, read_permissions=PROPOSAL_ADMIN, include_public_pool=False,
    )
    target_ids = query_service._scoped_ids(
        db, user, read_permissions=PROPOSAL_ADMIN, include_public_pool=False,
    )
    return db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.customer_id.in_(source_ids),
        (
            CustomerChangeProposal.target_customer_id.is_(None)
            | CustomerChangeProposal.target_customer_id.in_(target_ids)
        ),
    )


def _proposal_accesses(db, user, row):
    accesses = [_access(
        db, row.customer_id, user,
        action_permissions=PROPOSAL_ADMIN, allow_public_pool=False,
    )]
    if row.target_customer_id is not None:
        accesses.append(_access(
            db, row.target_customer_id, user,
            action_permissions=PROPOSAL_ADMIN, allow_public_pool=False,
        ))
    return accesses


@router.get("/change-proposals")
def proposals(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user=Depends(require_permission("customer:admin")),
):
    query = _proposal_scope_query(db, user)
    total = query.count()
    rows = query.order_by(CustomerChangeProposal.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok(page_result([
        _proposal_view(row, _proposal_accesses(db, user, row)) for row in rows
    ], total, page, page_size))


@router.post("/change-proposals", status_code=status.HTTP_201_CREATED)
def create_change_proposal(
    payload: ProposalCreate, db: Session = Depends(get_db),
    user=Depends(require_permission("customer:admin")),
):
    _access(db, payload.customer_id, user, action_permissions=PROPOSAL_ADMIN, allow_public_pool=False)
    if payload.target_customer_id is not None:
        _access(db, payload.target_customer_id, user, action_permissions=PROPOSAL_ADMIN, allow_public_pool=False)
    row = _service_call(proposal_service.create_proposal, db, **payload.model_dump(), proposed_by=_user_id(user))
    db.commit()
    return ok(_proposal_view(row, _proposal_accesses(db, user, row)), code=201)


def _proposal_action(db, user, proposal_id, operation, **kwargs):
    candidate = _proposal_scope_query(db, user).filter(
        CustomerChangeProposal.id == proposal_id,
    ).one_or_none()
    if candidate is None:
        _not_found()
    accesses = _proposal_accesses(db, user, candidate)
    if not _proposal_sensitive_visible(candidate, accesses):
        _not_found()
    row = _service_call(operation, db, proposal_id=proposal_id, actor_user_id=_user_id(user), **kwargs)
    db.commit()
    return ok(_proposal_view(row, accesses))


@router.post("/change-proposals/{proposal_id}/submit")
def submit_change_proposal(proposal_id: int, db: Session = Depends(get_db), user=Depends(require_permission("customer:admin"))):
    return _proposal_action(db, user, proposal_id, proposal_service.submit_proposal)


@router.post("/change-proposals/{proposal_id}/approve")
def approve_change_proposal(proposal_id: int, _payload: ProposalDecision, db: Session = Depends(get_db), user=Depends(require_permission("customer:admin"))):
    return _proposal_action(db, user, proposal_id, proposal_service.approve_proposal)


@router.post("/change-proposals/{proposal_id}/reject")
def reject_change_proposal(proposal_id: int, _payload: ProposalDecision, db: Session = Depends(get_db), user=Depends(require_permission("customer:admin"))):
    return _proposal_action(db, user, proposal_id, proposal_service.reject_proposal)


@router.post("/change-proposals/{proposal_id}/execute")
def execute_change_proposal(proposal_id: int, payload: ProposalExecute, db: Session = Depends(get_db), user=Depends(require_permission("customer:admin"))):
    return _proposal_action(db, user, proposal_id, proposal_service.execute_proposal, idempotency_key=payload.idempotency_key)
