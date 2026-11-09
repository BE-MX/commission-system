"""Transactional state transitions for customer-development collaboration."""
from hashlib import sha256
import json

from sqlalchemy import select

from app.core.time import beijing_now
from app.domestic_followup import collaboration_access as access
from app.domestic_followup import collaboration_projection as views
from app.domestic_followup.collaboration_models import (
    FollowupCollaborator, FollowupCollaborationEvent, FollowupHandoff, FollowupResponsibility,
)
from app.domestic_followup.collaboration_tasks import (
    ConflictError, active_tasks, execute_plan, package_tasks, plan_tasks, task_rows,
)
from app.domestic_followup.models import DomesticFollowup

project = views.project


def fingerprint(data):
    return sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_event(db, responsibility, actor, action, *, previous_owner=None, new_owner=None, reason=None,
                 handoff=None, details=None, request_key=None, request_hash=None):
    db.add(FollowupCollaborationEvent(
        customer_id=responsibility.customer_id, actor_user_id=actor, action=action, from_user_id=previous_owner,
        to_user_id=new_owner, reason=reason, responsibility_version=responsibility.version,
        handoff_id=handoff.id if handoff else None, details=details, idempotency_key=request_key,
        request_hash=request_hash,
    ))


def _reason(payload):
    if not payload.reason:
        raise ValueError("请填写原因")
    return payload.reason


def _receiver(db, customer, member, previous_owner):
    if not member or member == previous_owner:
        raise ValueError("请选择与原负责人不同的接收人")
    if not access.qualified(db, member, customer.id, lock=True):
        raise PermissionError("接收人当前缺少该客户范围或跟进读写权限")
    return member


def _selected_records(db, customer, record_ids):
    record_ids = set(record_ids)
    if not record_ids:
        return []
    found = set(db.scalars(select(DomesticFollowup.id).where(
        DomesticFollowup.customer_id == customer.id, DomesticFollowup.status == "confirmed",
        DomesticFollowup.shared_summary.is_not(None), DomesticFollowup.shared_summary != "",
        DomesticFollowup.id.in_(record_ids),
    )))
    if found != record_ids:
        raise ValueError("交接只可选入本客户已确认且有共享摘要的跟进记录")
    return sorted(found)


def _end_handoff(handoff, status, actor, reason):
    handoff.status = status
    handoff.pending_marker = None
    handoff.version += 1
    handoff.handled_at = beijing_now()
    handoff.handled_by_user_id = actor
    handoff.handling_reason = reason


def _change_owner(db, responsibility, recipient):
    responsibility.owner_user_id = recipient
    responsibility.status = "following"
    responsibility.stage = responsibility.stage or "new"
    responsibility.allow_future_contact = None
    collaborator = db.get(FollowupCollaborator, (responsibility.customer_id, recipient))
    if collaborator:
        db.delete(collaborator)


def _begin_handoff(db, customer, user, responsibility, payload):
    actor = access.user_id(user)
    owner = responsibility.owner_user_id
    offer = payload.action == "offer_handoff"
    receiver = _receiver(db, customer, payload.recipient_user_id if offer else actor, owner)
    if not access.qualified(db, owner, customer.id, lock=True):
        raise ConflictError("当前负责人已失去跟进资格，请联系协调员处理")
    tasks = active_tasks(db, customer.id, lock=True)
    rows = task_rows(tasks, owner)
    if offer:
        if not payload.summary:
            raise ValueError("请填写交接摘要")
        package = package_tasks(rows, plan_tasks(rows, payload))
        records = _selected_records(db, customer, payload.selected_record_ids)
    else:
        if payload.transfer_task_ids or payload.keep_task_ids or payload.cancel_task_ids or payload.selected_record_ids:
            raise ValueError("接手申请由负责人核对待办和共享记录")
        package = package_tasks(rows, {"transfer": [], "keep": [], "cancel": []})
        records = []
    handoff = FollowupHandoff(
        customer_id=customer.id, from_user_id=owner, recipient_user_id=receiver, requester_user_id=actor,
        kind="offer" if offer else "request", status="pending", pending_marker=1, version=1,
        responsibility_version=responsibility.version, reason=_reason(payload), summary=payload.summary,
        obstacle=payload.obstacle, commitment=payload.commitment, next_step=payload.next_step,
        tasks=package, selected_record_ids=records,
    )
    responsibility.status = "handoff"
    db.add(handoff)
    db.flush()
    return handoff


def _handle_handoff(db, customer, user, responsibility, handoff, payload):
    if handoff is None or payload.handoff_id != handoff.id or payload.handoff_version != handoff.version:
        raise ConflictError("交接单已变化，请刷新后重新核对")
    actor = access.user_id(user)
    if payload.action == "withdraw_handoff":
        _end_handoff(handoff, "withdrawn", actor, payload.reason)
        responsibility.status = "following"
        return {}
    if payload.action == "reject_handoff":
        _end_handoff(handoff, "rejected", actor, _reason(payload))
        responsibility.status = "following"
        return {}
    if (handoff.from_user_id != responsibility.owner_user_id
            or handoff.responsibility_version != responsibility.version - 1):
        raise ConflictError("当前责任或安排已变化，请撤回并重新发起交接")
    if not access.qualified(db, handoff.from_user_id, customer.id, lock=True):
        raise ConflictError("当前负责人已失去跟进资格，请联系协调员处理")
    recipient = _receiver(db, customer, handoff.recipient_user_id, handoff.from_user_id)
    tasks = active_tasks(db, customer.id, lock=True)
    rows = task_rows(tasks, handoff.from_user_id)
    if package_tasks(rows, handoff.tasks["plan"])["fingerprint"] != handoff.tasks["fingerprint"]:
        raise ConflictError("交接待办已变化，请刷新后重新核对并发起交接")
    if handoff.kind == "request":
        if not payload.summary:
            raise ValueError("请填写交接摘要")
        plan = plan_tasks(rows, payload)
        handoff.tasks = package_tasks(rows, plan)
        handoff.selected_record_ids = _selected_records(db, customer, payload.selected_record_ids)
        handoff.summary = payload.summary
        handoff.obstacle = payload.obstacle
        handoff.commitment = payload.commitment
        handoff.next_step = payload.next_step
    else:
        if payload.transfer_task_ids or payload.keep_task_ids or payload.cancel_task_ids or payload.selected_record_ids:
            raise ValueError("接收时请确认交接发起人已核对的待办和记录")
        plan = handoff.tasks["plan"]
    execute_plan(tasks, plan, recipient, actor)
    _end_handoff(handoff, "accepted", actor, payload.reason)
    _change_owner(db, responsibility, recipient)
    return plan


def _change_collaborator(db, customer, actor, owner, payload):
    member = payload.collaborator_user_id
    if member is None:
        raise ValueError("请选择协作人")
    existing = db.get(FollowupCollaborator, (customer.id, member))
    if payload.action == "remove_collaborator":
        if existing is None:
            raise ConflictError("该协作人已移除，请刷新")
        if any(task.assignee_user_id == member and task.task_type == "plan" and task.purpose == "development"
               for task in active_tasks(db, customer.id, lock=True)):
            raise ConflictError("该协作人仍有未完成的开发计划，请先处理相关待办")
        db.delete(existing)
    else:
        _receiver(db, customer, member, owner)
        if existing:
            raise ConflictError("该协作人已存在，请刷新")
        db.add(FollowupCollaborator(customer_id=customer.id, user_id=member, added_by_user_id=actor))
    return {"collaborator_user_id": member}


def _remaining_transition(db, customer, user, responsibility, handoff, payload):
    actor = access.user_id(user)
    action = payload.action
    owner = responsibility.owner_user_id
    if action == "claim":
        _change_owner(db, responsibility, actor)
        return {}
    reason = _reason(payload)
    if action == "open":
        if db.scalar(access.eligible_member_ids(customer.id).limit(1)) is None:
            raise ValueError("开放接手前，请先配置有跟进读写权限的协作范围成员")
        if any(task.task_type == "plan" and task.purpose in (None, "development")
               for task in active_tasks(db, customer.id, lock=True)):
            raise ConflictError("客户仍有开发或未分类待办，请先重派责任并核对待办")
        responsibility.status = "open"
        return {}
    if action == "reopen":
        responsibility.status = "following" if owner else "unassigned"
        responsibility.allow_future_contact = None
        return {}

    tasks = active_tasks(db, customer.id, lock=True)
    closing = action in ("release", "stop")
    coordinator = access.can_coordinate(db, user, customer)
    rows = task_rows(tasks, owner, coordinator, closing=closing)
    if closing and not coordinator and any(
        task.task_type == "plan" and task.purpose in (None, "development")
        and task.assignee_user_id != owner for task in tasks
    ):
        raise ConflictError("仍有其他人员负责的开发或未分类待办，请由协调员先处置")
    plan = plan_tasks(rows, payload, releasing=closing)
    recipient = payload.recipient_user_id
    if action == "reassign" or plan["transfer"]:
        recipient = _receiver(db, customer, recipient, owner)
    execute_plan(tasks, plan, recipient, actor)
    if handoff is not None:
        _end_handoff(handoff, "invalidated", actor, reason)
    if action == "reassign":
        _change_owner(db, responsibility, recipient)
    elif action == "release":
        responsibility.owner_user_id = None
        responsibility.status = "unassigned"
        responsibility.next_plan_date = None
        for member in db.scalars(select(FollowupCollaborator).where(
                FollowupCollaborator.customer_id == customer.id)):
            db.delete(member)
    elif action == "stop":
        if payload.allow_future_contact is None:
            raise ValueError("请说明客户是否允许未来联系")
        responsibility.status = "stopped"
        responsibility.allow_future_contact = payload.allow_future_contact
        responsibility.next_plan_date = None
    return plan


def apply_action(db, user, customer_id, payload):
    """Perform one mutation under the customer lock. Caller commits or rolls back."""
    customer = access.lock_customer(db, customer_id)
    if customer is None or not views.may_view(db, user, customer):
        raise LookupError("客户不存在或超出可见范围")
    actor = access.user_id(user)
    request_hash = fingerprint(payload.model_dump(exclude={"idempotency_key"}))
    replay = db.scalar(select(FollowupCollaborationEvent).where(
        FollowupCollaborationEvent.customer_id == customer_id,
        FollowupCollaborationEvent.actor_user_id == actor,
        FollowupCollaborationEvent.idempotency_key == payload.idempotency_key,
    ).with_for_update())
    if replay is not None:
        if replay.request_hash != request_hash:
            raise ConflictError("此请求编号已用于其他操作，请刷新")
        return project(db, user, customer)

    responsibility = db.scalar(select(FollowupResponsibility).where(
        FollowupResponsibility.customer_id == customer_id,
    ).with_for_update().execution_options(populate_existing=True))
    version = responsibility.version if responsibility else 0
    if payload.version != version:
        raise ConflictError("跟进责任已变化，请刷新后重新操作")
    handoff = views.pending_handoff(db, customer_id, lock=True)
    if payload.action not in views.capabilities(db, user, customer, responsibility, handoff, lock=True):
        raise PermissionError("当前责任状态或权限不允许该操作")
    if responsibility is None:
        responsibility = FollowupResponsibility(customer_id=customer_id, version=0, status="unassigned")
        db.add(responsibility)
    previous_owner = responsibility.owner_user_id
    responsibility.version += 1
    details = {}
    if payload.action in ("offer_handoff", "request_handoff"):
        handoff = _begin_handoff(db, customer, user, responsibility, payload)
    elif payload.action in ("accept_handoff", "reject_handoff", "withdraw_handoff"):
        details = _handle_handoff(db, customer, user, responsibility, handoff, payload)
    elif payload.action in ("add_collaborator", "remove_collaborator"):
        details = _change_collaborator(db, customer, actor, previous_owner, payload)
    else:
        details = _remaining_transition(db, customer, user, responsibility, handoff, payload)
    if responsibility.status in ("following", "handoff"):
        from app.domestic_followup.record_access import sync_development_date

        sync_development_date(db, responsibility)
    record_event(db, responsibility, actor, payload.action, previous_owner=previous_owner,
                 new_owner=responsibility.owner_user_id, reason=payload.reason, handoff=handoff,
                 details=details, request_key=payload.idempotency_key, request_hash=request_hash)
    db.flush()
    return project(db, user, customer)
