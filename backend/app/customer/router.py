"""Thin human-facing routes for unified customer operations."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.customer import evidence_service, proposal_router, qualification_service, query_service, workbench_service
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.models import CustomerAction, CustomerOpportunity, CustomerResearchTask
from app.customer.schemas import ActionUpdate, OpportunityUpdate, QualificationDecision
from app.customer.qualification_transaction import qualification_db
from app.customer.workflow_service import CustomerWorkflowConflict, CustomerWorkflowError, CustomerWorkflowNotFound
from app.sales_automation import router as acquisition_views
from app.sales_automation import public_pool_service, service as acquisition_service
from app.sales_automation import pool_rule_service
from app.sales_automation.pool_rule_schema import PoolRuleInput, PoolRuleSave, PoolConfiguredBatch
from app.sales_automation.schemas import (
    ProfileUpsert, PublicPoolBatchCreate, QualificationReviewSubmit,
    ResearchResultReview, SearchJobCreate,
)


router = APIRouter()
router.include_router(proposal_router.router)
CUSTOMER_READ = ("customer:read", "customer:read_all")
RESEARCH_READ = ("sales_automation:read", "customer:read_all")
OPPORTUNITY_READ = ("customer_opportunity:read", "customer:read_all")
ACTION_READ = ("customer_radar:read", "customer:read_all")
OPPORTUNITY_WRITE = ("customer_opportunity:write", "customer:admin")
ACTION_WRITE = ("customer_radar:write", "customer:admin")
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
    manage_permissions=("customer:admin",),
):
    try:
        return require_customer_access(
            db,
            customer_id=customer_id,
            user=user,
            action_permissions=set(action_permissions),
            manage_permissions=set(manage_permissions),
            allow_public_pool=allow_public_pool,
        )
    except CustomerAccessDenied:
        _not_found()


def _service_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (CustomerWorkflowNotFound, CustomerAccessDenied, acquisition_service.NotFoundError):
        args[0].rollback()
        _not_found()
    except (CustomerWorkflowConflict, acquisition_service.ConflictError) as exc:
        args[0].rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (CustomerWorkflowError, ValueError) as exc:
        args[0].rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception:
        args[0].rollback()
        raise


def _logical_record(db, model, object_type, object_id, user, permissions):
    owner = logical_owner_expression(model, object_type)
    result = db.query(model, owner.label("logical_customer_id")).filter(
        model.id == object_id,
        owner.in_(query_service._scoped_ids(
            db, user, read_permissions=permissions, include_public_pool=False,
        )),
    ).one_or_none()
    if result is None:
        _not_found()
    return result


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
    review_status: str | None = Query(None, pattern="^(pending|accepted|revision_requested|rejected)$"),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*RESEARCH_READ)),
):
    try:
        items, total = query_service.list_research_tasks(db, user, page=page, page_size=page_size, review_status=review_status)
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


@router.get("/public-pool/rules")
def public_pool_rules(db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    return ok(pool_rule_service.get_config(db))


@router.put("/public-pool/rules")
def save_public_pool_rules(payload: PoolRuleSave, db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    return ok(_service_call(pool_rule_service.save_config, db, payload, _user_id(user)))


@router.post("/public-pool/rules/preview")
def preview_public_pool_rules(payload: PoolRuleInput, db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    return ok(_service_call(pool_rule_service.preview, db, payload))


@router.post("/public-pool/rules/batches", status_code=status.HTTP_201_CREATED)
def create_configured_public_pool_batch(payload: PoolConfiguredBatch, db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    row = _service_call(pool_rule_service.create_configured_batch, db, payload, _user_id(user))
    return ok(acquisition_views._batch(row))

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

@router.post("/research-tasks/{task_id}/retry")
def retry_research_task(
    task_id: int,
    expected_attempt_count: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user=Depends(require_permission("sales_automation:admin")),
):
    from app.sales_automation.research_run_service import requeue_failed_task
    _, logical_id = _logical_record(
        db, CustomerResearchTask, "research_task", task_id, user, RESEARCH_READ,
    )
    access = _access(db, int(logical_id), user, action_permissions=RESEARCH_READ)
    row = _service_call(requeue_failed_task, db, task_id, _user_id(user), expected_attempt_count)
    return ok(query_service.serialize_research_task(row, access, customer_id=int(logical_id)))


@router.post("/research-tasks/{task_id}/result-review")
def review_research_task(task_id: int, payload: ResearchResultReview, db: Session = Depends(get_db), user=Depends(require_permission("sales_automation:admin"))):
    row, logical_id = _logical_record(
        db, CustomerResearchTask, "research_task", task_id, user, RESEARCH_READ,
    )
    access = _access(db, int(logical_id), user, action_permissions=RESEARCH_READ)
    reviewed = acquisition_views._call(
        public_pool_service.review_research_result, db, task_id,
        payload.review_status, reviewer_id=_user_id(user),
    )
    return ok(query_service.serialize_research_task(
        reviewed, access, include_content=True, customer_id=int(logical_id),
    ))

@router.get("/qualification-queue")
def qualification_queue(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=255),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*RESEARCH_READ)),
):
    return ok(qualification_service.list_queue(db, user, page=page, page_size=page_size, keyword=keyword))


@router.get("/qualification-queue/{task_id}")
def qualification_context(task_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission(*RESEARCH_READ))):
    try:
        return ok(_service_call(qualification_service.get_context, db, user, task_id))
    except CustomerAccessDenied:
        _not_found()


@router.post("/qualification-queue/{task_id}/decision")
def qualification_decision(task_id: int, payload: QualificationDecision, db: Session = Depends(qualification_db),
                           user=Depends(require_any_permission(*ACQUISITION_WRITE))):
    try:
        return ok(_service_call(qualification_service.submit_decision, db, user, task_id, payload))
    except CustomerAccessDenied:
        db.rollback()
        _not_found()


@router.get("/customers/{customer_id}/evidence")
def customer_evidence(customer_id: int, kind: str = Query("fact", pattern="^(fact|event)$"),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=255), db: Session = Depends(get_db),
    opportunity_id: int | None = Query(None, gt=0),
    target_status: str | None = Query(None, pattern="^(contacted|replied|quoted)$"),
    user=Depends(require_any_permission(*evidence_service.READ_PERMISSIONS)),
):
    try:
        return ok(evidence_service.list_evidence(db, user, customer_id, kind=kind, page=page,
                                               page_size=page_size, keyword=keyword,
                                               opportunity_id=opportunity_id, target_status=target_status))
    except CustomerAccessDenied:
        _not_found()

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
    scoped, logical_id = _logical_record(
        db, CustomerOpportunity, "opportunity", opportunity_id, user, OPPORTUNITY_WRITE,
    )
    access = _access(db, int(logical_id), user, action_permissions=OPPORTUNITY_WRITE, allow_public_pool=False)
    from app.insight.customer_opportunity_service import update_opportunity_status
    uid = _user_id(user)
    if not access.can_manage and scoped.owner_user_id != uid:
        raise HTTPException(status.HTTP_409_CONFLICT, "OPPORTUNITY_ACTOR_FORBIDDEN")
    _service_call(evidence_service.require_visible_selection, db, access,
                  fact_ids=payload.evidence_fact_ids, event_ids=payload.evidence_event_ids)
    row = _service_call(
        update_opportunity_status, db, opportunity_id, payload.status, payload.reason,
        uid, evidence_event_ids=tuple(payload.evidence_event_ids),
        evidence_fact_ids=tuple(payload.evidence_fact_ids), linked_order_id=payload.linked_order_id,
        close_reason_code=payload.close_reason_code, close_reason_text=payload.close_reason_text,
        can_manage=access.can_manage or scoped.customer_id != int(logical_id),
    )
    return ok(query_service.serialize_opportunity(row, customer_id=int(logical_id)))

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


@router.get("/workbench")
def workbench(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    view: str = Query("focus", pattern="^(focus|first_contact|today|overdue|high_priority|completed|unscheduled|upcoming|snoozed|all)$"),
    scope: str = Query("mine", pattern="^(mine|visible)$"),
    keyword: str | None = Query(None, max_length=255), customer_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db), user=Depends(require_any_permission(*ACTION_READ)),
):
    try:
        return ok(workbench_service.list_workbench(db, user, page=page, page_size=page_size,
                  view=view, scope=scope, keyword=keyword, customer_id=customer_id))
    except CustomerAccessDenied:
        _not_found()


@router.put("/actions/{action_id}")
def update_action(
    action_id: int, payload: ActionUpdate, db: Session = Depends(get_db),
    user=Depends(require_any_permission("customer_radar:write", "customer:admin")),
):
    scoped, logical_id = _logical_record(
        db, CustomerAction, "action", action_id, user, ACTION_WRITE,
    )
    access = _access(db, int(logical_id), user, action_permissions=ACTION_WRITE, allow_public_pool=False)
    from app.insight import customer_radar_service as service
    uid = _user_id(user)
    linked = db.get(CustomerOpportunity, scoped.opportunity_id) if scoped.opportunity_id else None
    if not access.can_manage and (
        scoped.owner_user_id != uid or linked is not None and linked.owner_user_id != uid
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "ACTION_OWNER_REQUIRED")
    can_manage = access.can_manage or scoped.customer_id != int(logical_id)
    if payload.operation == "complete":
        row = _service_call(
            service.complete_action, db, action_id, uid, payload.feedback, payload.note,
            outcome_code=payload.outcome_code or "other", channel=payload.channel,
            occurred_at=payload.occurred_at, summary=payload.summary, next_step=payload.next_step,
            next_step_due_at=payload.next_step_due_at, followup_action_type=payload.followup_action_type,
            followup_channel=payload.followup_channel,
            can_manage=can_manage,
        )
    elif payload.operation == "dismiss":
        row = _service_call(service.dismiss_action, db, action_id, uid, reason_code=payload.reason_code or "user_dismissed", note=payload.note, can_manage=can_manage)
    elif payload.operation == "snooze":
        if payload.snoozed_until is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "snoozed_until必填")
        row = _service_call(service.snooze_action, db, action_id, uid, payload.snoozed_until, can_manage=can_manage)
    else:
        row = _service_call(service.submit_feedback, db, action_id, payload.feedback or "", payload.note, uid, can_manage=can_manage)
    return ok(query_service.serialize_action(row, customer_id=int(logical_id)))
