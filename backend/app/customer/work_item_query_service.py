"""Permission-scoped work item projections with mutually exclusive views."""

from sqlalchemy import and_, exists, or_, case, func
from datetime import timedelta

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.models import CustomerAccount, CustomerAction, CustomerAssignment
from app.customer.pcw_models import CustomerWorkItem, MaintenanceOccurrence
from app.customer.pcw_overview_service import _scope_customer_ids
from app.customer.query_service import iso_beijing, serialize_action
from app.customer.workbench_models import CustomerDelegation, WorkItemDependency, WorkItemEvent
from app.customer.work_item_service import READ, WRITE, TERMINAL, allowed_operations, item_access, live_user

POLICY_VERSION = "workbench_v2"


def needs_me(item, now=None):
    now = now or beijing_now()
    if item.state == "resolved" and item.result_validity == "review_required":
        return True
    if item.state in {"open", "decision_required", "blocked"}:
        return item.review_at is None or item.review_at <= now
    if item.state == "waiting":
        return item.review_at is not None and item.review_at <= now
    return False


def scoped_items(db, user, *, customer_scope="primary", action_scope="mine", customer_id=None, keyword=None):
    user = live_user(db, user)
    if not set(user.get("permissions", [])) & set(READ) and "super_admin" not in user.get("roles", []):
        raise pcw_errors.customer_not_found()
    if customer_scope not in {"primary", "collaborator", "authorized"} or action_scope not in {"mine", "visible"}:
        raise pcw_errors.bad_request("工作台范围不合法", error_code="WORKBENCH_SCOPE_INVALID")
    perms = set(user.get("permissions") or [])
    if "super_admin" in (user.get("roles") or []):
        perms.add("customer:read_all")
    ids = _scope_customer_ids(db, actor_user_id=int(user["sub"]), perms=perms, customer_scope=customer_scope)
    owner = logical_owner_expression(CustomerWorkItem, "work_item")
    query = db.query(CustomerWorkItem).join(CustomerAccount, CustomerAccount.id == owner).filter(owner.in_(ids))
    if customer_id is not None:
        from app.customer.access_service import require_customer_access, CustomerAccessDenied
        try:
            access = require_customer_access(db, customer_id=customer_id, user=user, action_permissions=READ, manage_permissions=("customer:admin",))
        except CustomerAccessDenied as exc:
            raise pcw_errors.customer_not_found() from exc
        query = query.filter(owner == access.customer_id)
    if action_scope == "mine":
        mine = exists().where(and_(CustomerAction.work_item_id == CustomerWorkItem.id,
                                  CustomerAction.owner_user_id == int(user["sub"])))
        live_old_owner = exists().where(and_(
            CustomerAssignment.customer_id == owner,
            CustomerAssignment.user_id == CustomerWorkItem.owner_user_id,
            CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None)))
        live_new_primary = exists().where(and_(
            CustomerAssignment.customer_id == owner,
            CustomerAssignment.user_id == int(user["sub"]),
            CustomerAssignment.assignment_role == "primary",
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None)))
        query = query.filter(or_(CustomerWorkItem.owner_user_id == int(user["sub"]),
            and_(CustomerWorkItem.owner_user_id.is_(None), mine),
            and_(CustomerWorkItem.owner_user_id.is_(None), ~exists().where(CustomerAction.work_item_id == CustomerWorkItem.id)),
            and_(CustomerWorkItem.owner_user_id.is_not(None), ~live_old_owner, live_new_primary)))
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(CustomerWorkItem.title.ilike(pattern), CustomerAccount.display_name.ilike(pattern),
            CustomerAccount.customer_code.ilike(pattern)))
    return query


def serialize_item(db, user, item, access=None, *, admissions=None):
    user = live_user(db, user)
    if access is None:
        _, access = item_access(db, user, item.id)
    account = db.get(CustomerAccount, access.customer_id)
    can_write = access.can_manage or bool(set(user.get("permissions") or []) & set(WRITE)) and item.owner_user_id in (None, access.actor_user_id)
    actions = db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
        logical_owner_expression(CustomerAction, "action") == access.customer_id).order_by(CustomerAction.action_round).all()
    occurrences = {row.current_action_id: row for row in db.query(MaintenanceOccurrence).filter(
        MaintenanceOccurrence.current_action_id.in_([row.id for row in actions])).all()}
    serialized_actions = []
    for action in actions:
        data = serialize_action(action, customer_id=access.customer_id)
        data.update({"work_item_id": item.id, "work_item_state": item.state, "work_item_version": item.row_version,
                     "row_version": action.row_version, "can_operate": can_write
                     and item.state not in {"paused", "resolved", "cancelled"} and item.source_valid
                     and data["effective_status"] == "pending"
                     and (access.can_manage or action.owner_user_id == access.actor_user_id)})
        occurrence = occurrences.get(action.id)
        data.update({"occurrence_id": occurrence.id if occurrence else None,
                     "occurrence_version": occurrence.occurrence_version if occurrence else None})
        serialized_actions.append(data)
    dependencies = [{"id": row.id, "source_domain": row.source_domain, "source_id": row.source_id, "title": row.title,
        "required": row.required, "status": row.observed_status, "source_revision": row.observed_revision,
        "source_valid": row.source_valid, "observed_at": iso_beijing(row.observed_at)} for row in db.query(WorkItemDependency).filter(WorkItemDependency.item_id == item.id)]
    from app.customer.delegation_service import serialize_delegation
    delegations = [serialize_delegation(db, row) for row in db.query(CustomerDelegation).filter(
        CustomerDelegation.item_id == item.id, CustomerDelegation.actor_user_id == access.actor_user_id)]
    if not can_write:
        for delegation in delegations:
            delegation["allowed_operations"] = []
    from app.customer.work_item_feedback_service import item_artifacts
    artifacts = item_artifacts(db, user, item, access)
    history = [{"event_id": row.id, "event_type": row.event_type, "from_state": row.from_state, "to_state": row.to_state,
        "reason": row.reason, "occurred_at": iso_beijing(row.occurred_at), "item_version": row.item_version,
        "evidence_refs": row.evidence_refs,
        "delivery_plan": (row.payload_json or {}).get("delivery_plan") if row.event_type == "delivery_plan_decided" else None,
        "delivery_decision": (row.payload_json or {}).get("delivery_decision") if row.event_type == "delivery_plan_decided" else None,
        "customer_decision": (row.payload_json or {}).get("customer_decision") if row.event_type in {"resolve", "revalidate"} else None}
        for row in db.query(WorkItemEvent).filter(WorkItemEvent.item_id == item.id).order_by(WorkItemEvent.id.desc()).limit(100)]
    return {"item_id": item.id, "customer_id": access.customer_id, "customer_name": account.display_name,
        "title": item.title, "goal_type": item.goal_type, "goal_definition": item.goal_definition,
        "state": item.state, "waiting_kind": item.waiting_kind, "review_at": iso_beijing(item.review_at),
        "pause_reason": item.pause_reason, "resume_condition": item.resume_condition, "row_version": item.row_version,
        "source_revision": item.source_revision, "source_valid": item.source_valid, "result_validity": item.result_validity,
        "resolution_summary": item.resolution_summary, "resolution_evidence": item.resolution_evidence,
        "can_operate": can_write, "allowed_operations": allowed_operations(item) if can_write else [],
        "actions": serialized_actions, "dependencies": dependencies, "delegations": delegations,
        "prepared_artifacts": artifacts, "history": history, "daily_admitted": item.id in (admissions or set()),
        "can_admit": can_write and needs_me(item) and item.id not in (admissions or set()),
        "deep_link": f"/customer-hub/radar?customer_id={access.customer_id}&item_id={item.id}", "updated_at": iso_beijing(item.updated_at)}


def get_item(db, user, item_id):
    item, access = item_access(db, user, item_id)
    from app.customer.work_item_source_service import reconcile_item_inputs
    reconcile_item_inputs(db, item)
    from app.customer.workbench_models import WorkbenchDailyPlan, WorkbenchAdmission
    from app.core.time import beijing_today
    admitted = {row[0] for row in db.query(WorkbenchAdmission.item_id).join(WorkbenchDailyPlan,
        WorkbenchDailyPlan.id == WorkbenchAdmission.plan_id).filter(WorkbenchDailyPlan.actor_user_id == int(user["sub"]),
        WorkbenchDailyPlan.business_date == beijing_today())}
    return serialize_item(db, user, item, access, admissions=admitted)


def actionable_predicate(now):
    return or_(and_(CustomerWorkItem.state == "resolved", CustomerWorkItem.result_validity == "review_required"),
        and_(CustomerWorkItem.state.in_(("open", "decision_required", "blocked")),
            or_(CustomerWorkItem.review_at.is_(None), CustomerWorkItem.review_at <= now)),
        and_(CustomerWorkItem.state == "waiting", CustomerWorkItem.review_at <= now),
        and_(CustomerWorkItem.state == "in_progress", exists().where(and_(
            CustomerAction.work_item_id == CustomerWorkItem.id, CustomerAction.status.in_(("pending", "snoozed")),
            func.coalesce(CustomerAction.business_due_at, CustomerAction.due_at, CustomerAction.planned_at) <= now))))


def ordered_items(query, *, focus="commitments"):
    priority = query.session.query(func.min(case((CustomerAction.priority == "urgent", 0),
        (CustomerAction.priority == "high", 1), else_=2))).filter(CustomerAction.work_item_id == CustomerWorkItem.id,
        CustomerAction.status.in_(("pending", "snoozed"))).correlate(CustomerWorkItem).scalar_subquery()
    due = query.session.query(func.min(func.coalesce(CustomerAction.business_due_at, CustomerAction.original_due_at,
        CustomerAction.due_at))).filter(CustomerAction.work_item_id == CustomerWorkItem.id,
        CustomerAction.status.in_(("pending", "snoozed"))).correlate(CustomerWorkItem).scalar_subquery()
    focus_rank = case((CustomerWorkItem.goal_type.in_(("reorder", "repurchase")) if focus == "reorder" else CustomerWorkItem.goal_type.in_(("inquiry", "sample")), 0), else_=1) if focus != "commitments" else case((CustomerWorkItem.id.is_(None), 0), else_=1)
    return query.order_by(func.coalesce(priority, 3), due.is_(None), due, focus_rank,
        CustomerWorkItem.review_at.is_(None), CustomerWorkItem.review_at, CustomerWorkItem.id)


def responsibility_summary(db, user):
    if not set(user.get("permissions", [])) & set(READ) and "super_admin" not in user.get("roles", []):
        return {"items": [], "total": 0, "count_unit": "work_item"}
    query = scoped_items(db, user, customer_scope="authorized", action_scope="mine")
    from app.customer.work_item_source_service import reconcile_item_inputs
    for item in query.order_by(CustomerWorkItem.id):
        reconcile_item_inputs(db, item)
    query = query.filter(actionable_predicate(beijing_now()))
    total = query.count()
    items = [{"source_domain": "customer", "item_id": row.id, "responsibility_id": f"customer:item:{row.id}:owner:{user['sub']}",
        "title": row.title, "state": row.state, "required_action": "复核结果依据" if row.result_validity == "review_required" else "查看事项并处理下一步",
        "due_at": iso_beijing(row.review_at), "updated_at": iso_beijing(row.updated_at),
        "deep_link": f"/customer-hub/radar?item_id={row.id}&customer_id={logical_id}"}
        for row, logical_id in query.with_entities(CustomerWorkItem, logical_owner_expression(CustomerWorkItem, "work_item")).order_by(CustomerWorkItem.review_at, CustomerWorkItem.id).limit(5)]
    return {"items": items, "total": total, "count_unit": "work_item"}


def list_items(db, user, *, view="need_me", customer_scope="primary", action_scope="mine", ended_state=None,
               customer_id=None, keyword=None, page=1, page_size=20, focus="commitments"):
    from app.customer.daily_plan_service import get_plan, plan_summary
    if view not in {"need_me", "in_progress", "ended"}:
        raise pcw_errors.bad_request("工作台视图不合法", error_code="WORKBENCH_VIEW_INVALID")
    query = scoped_items(db, user, customer_scope=customer_scope, action_scope=action_scope,
                        customer_id=customer_id, keyword=keyword)
    from app.customer.work_item_source_service import reconcile_item_inputs
    for item in query.order_by(CustomerWorkItem.id):
        reconcile_item_inputs(db, item)
    now = beijing_now()
    need = actionable_predicate(now)
    ended = and_(CustomerWorkItem.state.in_(TERMINAL), ~need)
    progressing = and_(~CustomerWorkItem.state.in_(TERMINAL), ~need)
    summary = {"items_need_me": query.filter(need).count(), "items_in_progress": query.filter(progressing).count(),
        "items_resolved": query.filter(CustomerWorkItem.state == "resolved", CustomerWorkItem.result_validity == "verified").count(),
        "items_cancelled": query.filter(CustomerWorkItem.state == "cancelled").count()}
    item_ids = query.with_entities(CustomerWorkItem.id)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    done = db.query(CustomerAction).filter(CustomerAction.work_item_id.in_(item_ids), CustomerAction.status == "done",
        CustomerAction.completed_at >= midnight, CustomerAction.completed_at < midnight + timedelta(days=1))
    if action_scope == "mine":
        done = done.filter(CustomerAction.owner_user_id == int(user["sub"]))
    summary["actions_done_today"] = done.count()
    summary["overdue_promises"] = db.query(CustomerAction.id).filter(CustomerAction.work_item_id.in_(item_ids),
        CustomerAction.status.in_(("pending", "snoozed")), CustomerAction.original_due_at < now).count()
    plan, admitted = get_plan(db, user)
    chosen = query.filter({"need_me": need, "in_progress": progressing, "ended": ended}[view])
    if view == "ended" and ended_state:
        chosen = chosen.filter(CustomerWorkItem.state == ended_state)
    total = chosen.count()
    rows = ordered_items(chosen, focus=focus).offset((page-1)*page_size).limit(page_size).all()
    queued = query.filter(need, ~CustomerWorkItem.id.in_(admitted)).count()
    return {"items": [serialize_item(db, user, item, admissions=admitted) for item in rows],
        "total": total, "page": page, "page_size": page_size, "count_unit": "work_item", "summary": summary,
        "capacity": plan_summary(db, plan, queued=queued),
        "data_as_of": iso_beijing(now), "policy_version": POLICY_VERSION}
