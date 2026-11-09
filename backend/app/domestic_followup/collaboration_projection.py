"""Permission-aware customer collaboration views."""
from sqlalchemy import func, or_, select

from app.auth.models import ArkUser
from app.core.time import beijing_today
from app.domestic.models import DomesticCustomer, DomesticCustomerCommission
from app.domestic_followup import collaboration_access as access, visibility
from app.domestic_followup.collaboration_models import (
    FollowupCollaborator, FollowupCollaborationEvent, FollowupHandoff,
)
from app.domestic_followup.collaboration_tasks import active_tasks, task_rows
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupConfig, DomesticFollowupTask

PENDING_DAYS_KEY = "collaboration_pending_handoff_days"


def pending_handoff(db, customer_id, *, lock=False):
    query = select(FollowupHandoff).where(
        FollowupHandoff.customer_id == customer_id, FollowupHandoff.pending_marker == 1,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def is_participant(handoff, actor):
    return actor in (handoff.from_user_id, handoff.recipient_user_id, handoff.requester_user_id)


def legacy_summary(db, user, customer):
    if not access.claims_allow(user, access.READ):
        return False
    actor = access.user_id(user)
    return (visibility.can_read_all(user) or customer.owner_user_id == actor
            or db.scalar(select(DomesticCustomerCommission.id).where(
                DomesticCustomerCommission.customer_id == customer.id,
                DomesticCustomerCommission.user_id == actor,
            ).limit(1)) is not None
            or db.scalar(select(DomesticFollowup.id).where(
                DomesticFollowup.customer_id == customer.id, DomesticFollowup.author_user_id == actor,
                DomesticFollowup.status == "confirmed",
            ).limit(1)) is not None
            or db.scalar(select(DomesticFollowupTask.id).where(
                DomesticFollowupTask.customer_id == customer.id,
                DomesticFollowupTask.assignee_user_id == actor,
            ).limit(1)) is not None)


def may_view(db, user, customer):
    if (access.has_summary_access(db, user, customer) or access.can_coordinate(db, user, customer)
            or legacy_summary(db, user, customer)):
        return True
    actor = access.user_id(user)
    return db.scalar(select(FollowupCollaborationEvent.id).where(
        FollowupCollaborationEvent.customer_id == customer.id,
        or_(FollowupCollaborationEvent.from_user_id == actor, FollowupCollaborationEvent.to_user_id == actor),
        FollowupCollaborationEvent.action.in_(("claim", "accept_handoff", "reassign", "release", "initialize")),
    ).limit(1)) is not None


def read_customer(db, user, customer_id):
    customer = db.get(DomesticCustomer, customer_id)
    if customer is None or not may_view(db, user, customer):
        raise LookupError("客户不存在或超出可见范围")
    return customer


def user_names(db, ids):
    return dict(db.execute(select(ArkUser.id, ArkUser.real_name).where(ArkUser.id.in_(set(ids)))).all())


def capabilities(db, user, customer, responsibility, handoff, *, lock=False):
    actor = access.user_id(user)
    eligible = access.eligible_actor(db, user, customer, lock=lock)
    coordinator = access.can_coordinate(db, user, customer, lock=lock)
    owner_id = responsibility.owner_user_id if responsibility else None
    is_owner = eligible and owner_id == actor
    state = responsibility.status if responsibility else "unassigned"
    actions = []
    if handoff and (is_owner or (eligible and is_participant(handoff, actor)) or coordinator):
        if handoff.requester_user_id == actor or coordinator:
            actions.append("withdraw_handoff")
        reviewer = handoff.recipient_user_id if handoff.kind == "offer" else handoff.from_user_id
        if eligible and reviewer == actor:
            actions.append("reject_handoff")
            if customer.status == 1 and state == "handoff":
                actions.append("accept_handoff")
    if customer.status != 1:
        return actions
    if state == "stopped":
        return [*actions, "reopen"] if is_owner or coordinator else actions
    if coordinator:
        if state == "unassigned":
            actions.append("open")
        actions.extend(("reassign", "stop"))
    if state == "open" and eligible:
        actions.append("claim")
    if is_owner:
        if not handoff and state == "following":
            actions.extend(("offer_handoff", "release"))
        actions.extend(("add_collaborator", "remove_collaborator"))
        if "stop" not in actions:
            actions.append("stop")
    if eligible and owner_id and owner_id != actor and state == "following" and not handoff:
        actions.append("request_handoff")
    return actions


def pending_handoff_days(db):
    row = db.get(DomesticFollowupConfig, PENDING_DAYS_KEY)
    return row.value if row and type(row.value) is int and 1 <= row.value <= 30 else 3


def coordination_reasons(db, customer, responsibility, handoff, *, pending_days=None):
    if responsibility is None:
        return []
    today = beijing_today()
    reasons = []
    if customer.status != 1 and (responsibility.owner_user_id or handoff or active_tasks(db, customer.id)):
        reasons.append("customer_inactive")
    if responsibility.status == "unassigned":
        reasons.append("unassigned")
    if responsibility.owner_user_id and not access.qualified(db, responsibility.owner_user_id, customer.id):
        reasons.append("owner_ineligible")
    if handoff:
        if not access.qualified(db, handoff.recipient_user_id, customer.id):
            reasons.append("recipient_ineligible")
        threshold = pending_handoff_days(db) if pending_days is None else pending_days
        if (today - handoff.created_at.date()).days >= threshold:
            reasons.append("handoff_overdue")
    if responsibility.status in ("following", "handoff") and customer.status == 1:
        development = [task for task in active_tasks(db, customer.id)
                       if task.task_type == "plan" and task.purpose == "development"]
        if responsibility.next_plan_date is not None and any(task.due_date >= today for task in development):
            return reasons
        last = responsibility.last_progress_at or responsibility.created_at
        if (today - last.date()).days >= 30:
            reasons.append("no_progress")
        if any((today - task.due_date).days >= 30 for task in development):
            reasons.append("development_task_overdue")
    return reasons


def _handoff_view(db, handoff, names, *, include_selected):
    if handoff is None:
        return None
    data = {
        "id": handoff.id,
        "version": handoff.version,
        "status": handoff.status,
        "kind": handoff.kind,
        "recipient_user_id": handoff.recipient_user_id,
        "recipient_name": names.get(handoff.recipient_user_id),
        "requester_user_id": handoff.requester_user_id,
        "from_user_id": handoff.from_user_id,
        "reason": handoff.reason,
        "summary": handoff.summary,
        "obstacle": handoff.obstacle,
        "commitment": handoff.commitment,
        "next_step": handoff.next_step,
        "tasks": handoff.tasks.get("preview", []),
        "created_at": handoff.created_at,
    }
    if include_selected and handoff.selected_record_ids:
        records = db.execute(select(DomesticFollowup.id, DomesticFollowup.followup_date,
                                    DomesticFollowup.shared_summary, DomesticFollowup.author_user_id).where(
            DomesticFollowup.id.in_(handoff.selected_record_ids),
            DomesticFollowup.customer_id == handoff.customer_id,
            DomesticFollowup.status == "confirmed",
        ).order_by(DomesticFollowup.followup_date.desc(), DomesticFollowup.id.desc()))
        data["selected_records"] = [
            {"id": rid, "date": when, "summary": summary, "author_user_id": author}
            for rid, when, summary, author in records if summary
        ]
    return data


def project(db, user, customer, *, include_coordination=True):
    responsibility = access.responsibility_for(db, customer.id)
    owner_id = responsibility.owner_user_id if responsibility else None
    handoff = pending_handoff(db, customer.id)
    actor = access.user_id(user)
    coordinator = access.can_coordinate(db, user, customer)
    summary_allowed = coordinator or access.has_summary_access(db, user, customer) or legacy_summary(db, user, customer)
    can_preview = handoff and (coordinator or (
        is_participant(handoff, actor) and access.qualified(db, actor, customer.id)
    ))
    collaborators = []
    if access.has_history_access(db, user, customer):
        collaborators = db.scalars(select(FollowupCollaborator.user_id).where(
            FollowupCollaborator.customer_id == customer.id,
        ).order_by(FollowupCollaborator.user_id)).all()
    if not summary_allowed:
        owner_id, responsibility = None, None
    names = user_names(db, [owner_id, *collaborators, handoff.recipient_user_id if handoff else None])
    return {
        "customer_id": customer.id,
        "owner_user_id": owner_id,
        "owner_name": names.get(owner_id),
        "state": responsibility.status if responsibility else ("unassigned" if summary_allowed else None),
        "stage": responsibility.stage if responsibility else None,
        "version": responsibility.version if responsibility else (0 if summary_allowed else None),
        "last_progress_at": responsibility.last_progress_at if responsibility else None,
        "next_plan_date": responsibility.next_plan_date if responsibility else None,
        "allow_future_contact": (responsibility.allow_future_contact
                                 if responsibility and (coordinator or access.has_history_access(db, user, customer))
                                 else None),
        "collaborators": [{"user_id": member, "name": names.get(member)} for member in collaborators],
        "available_actions": capabilities(db, user, customer, responsibility, handoff),
        "handoff": _handoff_view(db, handoff, names, include_selected=True) if can_preview else None,
        "coordination_reasons": (coordination_reasons(db, customer, responsibility, handoff)
                                 if include_coordination and coordinator else []),
    }


def candidates(db, user, customer):
    responsibility = access.responsibility_for(db, customer.id)
    actor = access.user_id(user)
    if not (access.can_coordinate(db, user, customer) or
            (responsibility and responsibility.owner_user_id == actor
             and access.eligible_actor(db, user, customer))):
        raise PermissionError("仅负责人或该客户协调员可以查看候选人")
    members = db.execute(select(ArkUser.id, ArkUser.real_name).where(
        ArkUser.id.in_(access.eligible_member_ids(customer.id)),
        ArkUser.id != actor,
    ).order_by(ArkUser.real_name, ArkUser.id)).all()
    return [{"user_id": member, "name": name} for member, name in members]


def task_preflight(db, user, customer, action=None):
    responsibility = access.responsibility_for(db, customer.id)
    owner_id = responsibility.owner_user_id if responsibility else None
    coordinator = access.can_coordinate(db, user, customer)
    if not coordinator and (owner_id != access.user_id(user) or not access.eligible_actor(db, user, customer)):
        raise PermissionError("仅负责人或该客户协调员可以核对待办")
    closing = action in ("release", "stop")
    admin_task_selection = coordinator and action not in ("offer_handoff", "accept_handoff")
    return {"items": task_rows(active_tasks(db, customer.id), owner_id, admin_task_selection, closing=closing)}


def events(db, user, customer, page, page_size):
    actor = access.user_id(user)
    coordinator = access.can_coordinate(db, user, customer)
    filters = [FollowupCollaborationEvent.customer_id == customer.id]
    # The reason and task decisions may contain personal/business details.
    if not access.has_history_access(db, user, customer) and not coordinator:
        filters.append(or_(FollowupCollaborationEvent.actor_user_id == actor,
                           FollowupCollaborationEvent.from_user_id == actor,
                           FollowupCollaborationEvent.to_user_id == actor))
        filters.append(FollowupCollaborationEvent.action.not_in(("offer_handoff", "request_handoff")))
    total = db.scalar(select(func.count()).select_from(FollowupCollaborationEvent).where(*filters))
    records = db.scalars(select(FollowupCollaborationEvent).where(*filters)
                         .order_by(FollowupCollaborationEvent.id.desc())
                         .offset((page - 1) * page_size).limit(page_size)).all()
    handoffs = {handoff.id: handoff for handoff in db.scalars(select(FollowupHandoff).where(
        FollowupHandoff.id.in_([event.handoff_id for event in records if event.handoff_id]),
        FollowupHandoff.status != "pending",
    ))}
    names = user_names(db, [event.actor_user_id for event in records])

    def history_bundle(event):
        handoff = handoffs.get(event.handoff_id)
        if handoff and (coordinator or is_participant(handoff, actor)):
            return {"id": handoff.id, "kind": handoff.kind, "status": handoff.status,
                    "reason": handoff.reason, "handled_at": handoff.handled_at}
        return None

    return {"total": total, "items": [
        {"id": event.id, "action": event.action, "actor_user_id": event.actor_user_id,
         "actor_name": names.get(event.actor_user_id), "from_user_id": event.from_user_id,
         "to_user_id": event.to_user_id, "reason": event.reason, "created_at": event.created_at,
         "handoff_outcome": history_bundle(event)}
        for event in records
    ]}
