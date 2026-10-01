"""Persistent Beijing-day capacity; terminal items do not release admissions."""

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.time import beijing_now, beijing_today
from app.customer import pcw_errors
from app.customer.models import CustomerAction
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.pcw_workitem_service import _require_version
from app.customer.workbench_models import WorkbenchAdmission, WorkbenchDailyPlan


def _is_urgent(db, item):
    now = beijing_now()
    return db.query(CustomerAction.id).filter(CustomerAction.work_item_id == item.id,
        CustomerAction.status.in_(("pending", "snoozed"))).filter(
        (CustomerAction.priority == "urgent") | (CustomerAction.business_due_at <= now)).first() is not None


def _entry(db, plan, item, kind, reason, before):
    db.add(WorkbenchAdmission(plan_id=plan.id, item_id=item.id, admission_type=kind,
        reason=reason, budget_before=before, budget_after=plan.budget))


def get_plan(db, user):
    from app.customer.work_item_query_service import actionable_predicate, scoped_items, ordered_items
    actor = int(user["sub"])
    day = beijing_today()
    plan = db.query(WorkbenchDailyPlan).filter_by(actor_user_id=actor, business_date=day).with_for_update().one_or_none()
    if plan is None:
        try:
            with db.begin_nested():
                plan = WorkbenchDailyPlan(actor_user_id=actor, business_date=day,
                    policy_version="workbench_v2", budget=get_settings().PCW_DAILY_ITEM_BUDGET)
                db.add(plan)
                db.flush()
        except IntegrityError:
            plan = db.query(WorkbenchDailyPlan).filter_by(actor_user_id=actor, business_date=day).populate_existing().with_for_update().one()
    if not plan.initialized:
        candidates = ordered_items(scoped_items(db, user, customer_scope="authorized").filter(actionable_predicate(beijing_now()))).all()
        urgent = [item for item in candidates if _is_urgent(db, item)]
        ordinary = [item for item in candidates if item not in urgent][:plan.budget]
        for item in urgent:
            _entry(db, plan, item, "urgent_override", "源行动明确紧急或承诺已到期", plan.budget)
        for item in ordinary:
            _entry(db, plan, item, "ordinary", "今日首次入选", plan.budget)
        plan.initialized = True
        plan.row_version += 1
        db.flush()
    admitted = {row.item_id for row in db.query(WorkbenchAdmission).filter(WorkbenchAdmission.plan_id == plan.id)}
    return plan, admitted


def plan_summary(db, plan, *, queued=0):
    entries = db.query(WorkbenchAdmission).filter(WorkbenchAdmission.plan_id == plan.id).all()
    ordinary = sum(row.admission_type != "urgent_override" for row in entries)
    return {"plan_id": plan.id, "version": plan.row_version, "business_date": plan.business_date.isoformat(),
        "budget": plan.budget, "admitted": ordinary, "urgent": len(entries) - ordinary, "queued": queued,
        "policy_version": plan.policy_version}


def admit_item(db, user, payload, idempotency_key):
    from app.customer.work_item_service import item_access
    from app.customer.work_item_query_service import actionable_predicate
    from app.customer.pcw_models import CustomerWorkItem
    item, access = item_access(db, user, payload["item_id"], write=True)
    if db.query(CustomerWorkItem.id).filter(CustomerWorkItem.id == item.id, actionable_predicate(beijing_now())).first() is None:
        raise pcw_errors.conflict("该事项当前无需本人处理", error_code="ITEM_NOT_ACTIONABLE")

    def execute():
        plan, admitted = get_plan(db, user)
        _require_version(plan.row_version, payload["expected_plan_version"], "PLAN_VERSION_CONFLICT", "current_plan_version")
        if item.id in admitted:
            return {"capacity": plan_summary(db, plan), "item_id": item.id, "daily_admitted": True}
        entries = db.query(WorkbenchAdmission).filter(WorkbenchAdmission.plan_id == plan.id,
            WorkbenchAdmission.admission_type != "urgent_override").count()
        before = plan.budget
        kind = "ordinary"
        reason = str(payload.get("reason") or "主动领取事项").strip()
        if _is_urgent(db, item):
            kind = "urgent_override"
            reason = "源行动明确紧急或承诺已到期"
        elif entries >= plan.budget:
            if not payload.get("allow_one_extra"):
                raise pcw_errors.conflict("今日普通容量已满", error_code="DAILY_CAPACITY_EXCEEDED")
            if not str(payload.get("reason") or "").strip():
                raise pcw_errors.bad_request("增额需要具体原因", error_code="ADMISSION_REASON_REQUIRED")
            kind = "manual_extra"
            plan.budget += 1
        _entry(db, plan, item, kind, reason[:1000], before)
        plan.row_version += 1
        plan.updated_at = beijing_now()
        db.flush()
        return {"capacity": plan_summary(db, plan), "item_id": item.id, "daily_admitted": True}

    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id, operation_scope="workbench_admission",
        idempotency_key=idempotency_key, request_payload=payload, execute=execute)
    return result
