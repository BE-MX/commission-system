"""Single versioned lifecycle entry point. Source modules retain execution ownership."""

from datetime import datetime

from app.core.time import beijing_now, to_beijing_naive
from app.customer import pcw_errors
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.models import CustomerAction, CustomerAssignment
from app.customer.pcw_models import CustomerWorkItem
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.pcw_workitem_service import _require_version
from app.customer.work_item_evidence_service import validate_evidence
from app.customer.workbench_models import CustomerDelegation, WorkItemDependency, WorkItemEvent
from app.customer.workflow_service import _account_for_update

READ = ("customer_pcw:read", "customer_radar:read", "customer:read", "customer:read_all")
WRITE = ("customer_pcw:write", "customer_radar:write", "customer:admin")
TERMINAL = frozenset({"resolved", "cancelled"})


def live_user(db, user):
    from app.auth.service import get_live_user_authorization
    roles, permissions = get_live_user_authorization(db, int(user["sub"]))
    return {**user, "roles": sorted(set(roles) & set(user.get("roles", []))),
        "permissions": sorted(set(permissions) & set(user.get("permissions", [])))}


def item_access(db, user, item_id, *, write=False, lock=False):
    user = live_user(db, user)
    candidate = db.query(CustomerWorkItem, logical_owner_expression(CustomerWorkItem, "work_item").label("logical_id")).filter(
        CustomerWorkItem.id == item_id).one_or_none()
    if candidate is None:
        raise pcw_errors.customer_not_found()
    try:
        access = require_customer_access(db, customer_id=int(candidate.logical_id), user=user,
            action_permissions=WRITE if write else READ, manage_permissions=("customer:admin",))
    except CustomerAccessDenied as exc:
        raise pcw_errors.customer_not_found() from exc
    item = candidate[0]
    if lock:
        _account_for_update(db, access.customer_id)
        from app.customer.logical_customer_service import logical_root_predicate
        item = db.query(CustomerWorkItem).filter(CustomerWorkItem.id == item_id,
            logical_root_predicate(CustomerWorkItem, "work_item", access.customer_id)).populate_existing().with_for_update().one_or_none()
        if item is None:
            raise pcw_errors.customer_not_found()
        reconcile_assignment(db, item, access.customer_id)
    if write and item.owner_user_id not in (None, access.actor_user_id) and not access.can_manage:
        raise pcw_errors.forbidden("仅事项负责人或管理员可以操作", error_code="WORK_ITEM_OWNER_REQUIRED")
    return item, access


def reconcile_assignment(db, item, logical_customer_id, *, read_only=False):
    """Fence old work when its owner loses this customer's live assignment."""
    if item.owner_user_id is None:
        return item
    assigned = db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == logical_customer_id,
        CustomerAssignment.user_id == item.owner_user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None)).first()
    if assigned is not None:
        return item
    primary = db.query(CustomerAssignment.user_id).filter(
        CustomerAssignment.customer_id == logical_customer_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None)).one_or_none()
    next_owner = primary.user_id if primary else None
    if read_only:
        raise pcw_errors.conflict("客户负责人已变化，请停止当前委派", error_code="WORK_ITEM_OWNER_CHANGED")
    if next_owner is None and item.resume_condition == "owner_unassigned":
        return item
    previous = item.state
    old_owner = item.owner_user_id
    item.source_revision += 1
    if next_owner is None:
        item.source_valid = False
        item.resume_condition = "owner_unassigned"
    else:
        item.owner_user_id = next_owner
        item.resume_condition = "客户负责人已变化，请核对未完成行动与目标依据"
    if item.state == "resolved":
        item.result_validity = "review_required"
    elif item.state not in TERMINAL and item.state != "paused":
        item.state = "blocked"
        item.review_at = beijing_now()
    freeze_delegations(db, item, reason="客户负责人或可访问范围已变化")
    for action in db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
            CustomerAction.owner_user_id == old_owner,
            CustomerAction.status.in_(("pending", "snoozed"))).order_by(CustomerAction.id).with_for_update():
        if next_owner is not None:
            action.owner_user_id = next_owner
            action.row_version += 1
            action.updated_at = beijing_now()
    record_event(db, item, actor=None, operation="assignment_changed", previous=previous,
        reason="客户负责人已变化，旧委派已停止，待新负责人核对",
        payload={"previous_owner_user_id": old_owner, "new_owner_user_id": next_owner})
    return item


def allowed_operations(item):
    if item.state in TERMINAL:
        result = ["reopen"]
        if item.state == "resolved" and item.result_validity == "review_required":
            result.append("revalidate")
        return result
    if item.state == "paused":
        return (["reverify"] if not item.source_valid else ["resume"]) + ["cancel"]
    if not item.source_valid:
        return ["reverify", "cancel"]
    result = ["start", "wait", "decide", "block", "pause", "cancel", "snooze"]
    if item.source_valid and item.state != "blocked":
        result.append("resolve")
        if item.goal_type == "delivery_exception":
            result.append("record_delivery_plan")
    return result


def record_event(db, item, *, actor, operation, previous, reason, evidence=None, payload=None):
    item.row_version = int(item.row_version) + 1
    item.updated_at = beijing_now()
    event = WorkItemEvent(item_id=item.id, actor_user_id=actor, event_type=operation,
        from_state=previous, to_state=item.state, reason=reason, evidence_refs=evidence or [],
        input_revision=item.source_revision, item_version=item.row_version, payload_json=payload or {})
    db.add(event)
    db.flush()
    return event


def apply_source_transition(db, item, *, operation, reason, evidence=None):
    """Source-only acceptance after the caller verified its persisted source object."""
    from app.customer.models import CustomerAccount
    logical_id = db.query(logical_owner_expression(CustomerWorkItem, "work_item")).filter(CustomerWorkItem.id == item.id).scalar()
    _account_for_update(db, logical_id)
    item = db.query(CustomerWorkItem).filter(CustomerWorkItem.id == item.id).populate_existing().with_for_update().one()
    if item.state in TERMINAL:
        return None
    if operation == "resolved" and item.state == "paused":
        return None
    if operation not in {"resolved", "cancelled"}:
        raise ValueError("Unsupported source transition")
    if operation == "resolved":
        if item.goal_type not in {"inquiry", "inquiry_sla"} or not evidence:
            raise pcw_errors.conflict("源目标验收不匹配", error_code="GOAL_EVIDENCE_MISMATCH")
        require_dependencies(db, item)
    actions = db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
        CustomerAction.status.in_(("pending", "snoozed"))).order_by(CustomerAction.id).with_for_update().all()
    for action in actions:
        action.status = "cancelled"
        action.dismissal_reason = reason[:1000]
        action.row_version += 1
    previous = item.state
    item.state = operation
    item.resolution_summary = reason
    if operation == "resolved":
        item.result_validity = "verified"
        item.resolution_evidence = evidence
        item.resolved_at = beijing_now()
    freeze_delegations(db, item, terminal=True, reason=reason)
    return record_event(db, item, actor=None, operation="source_" + operation,
        previous=previous, reason=reason, evidence=evidence)


def freeze_delegations(db, item, *, terminal=False, actor=None, reason=""):
    rows = db.query(CustomerDelegation).filter(CustomerDelegation.item_id == item.id).order_by(
        CustomerDelegation.id).with_for_update().all()
    for delegation in rows:
        if delegation.status in {"cancelled", "completed"}:
            continue
        if delegation.status != "paused" or terminal:
            delegation.status = "cancelled" if terminal else "paused"
            delegation.pause_origin = "item"
            delegation.pause_reason = reason[:1000]
            delegation.generation += 1
            delegation.row_version += 1
            delegation.cancel_requested = delegation.last_run_id is not None
            delegation.updated_at = beijing_now()
            if delegation.last_run_id:
                from app.agent_runtime.models import AgentRun
                run = db.query(AgentRun).filter(AgentRun.id == delegation.last_run_id).with_for_update().one_or_none()
                if run is not None and run.status not in {"completed", "failed", "cancelled", "ambiguous"}:
                    run.cancel_requested = True


def require_dependencies(db, item, *, actor_user_id=None, completing_action_id=None):
    from app.customer.work_item_source_service import observe_dependency
    gaps = []
    for action in db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
            CustomerAction.required_for_resolution.is_(True)).order_by(CustomerAction.id).with_for_update():
        if action.status != "done" and action.id != completing_action_id:
            gaps.append({"action_id": action.id, "status": action.status})
    for dependency in db.query(WorkItemDependency).filter(WorkItemDependency.item_id == item.id,
            WorkItemDependency.required.is_(True)).order_by(WorkItemDependency.id).with_for_update().all():
        status, revision, valid = observe_dependency(db, dependency, item, actor_user_id=actor_user_id)
        completing = dependency.source_domain == "action" and str(dependency.source_id) == str(completing_action_id)
        if not valid or status not in {"done", "completed", "fulfilled", "delivered"} and not completing:
            gaps.append({"dependency_id": dependency.id, "status": status})
    if gaps:
        raise pcw_errors.conflict("必要交付尚未验收", error_code="REQUIRED_DEPENDENCY_OPEN", details={"gaps": gaps})


def apply_transition(db, item, access, payload):
    from app.customer.work_item_source_service import reconcile_item_inputs
    reconcile_item_inputs(db, item)
    operation = payload["operation"]
    if operation not in allowed_operations(item):
        raise pcw_errors.conflict("当前状态不允许该操作", error_code="WORK_ITEM_TRANSITION_INVALID")
    _require_version(item.row_version, payload["expected_item_version"], "WORK_ITEM_VERSION_CONFLICT", "current_item_version")
    reason = str(payload.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        raise pcw_errors.bad_request("请填写具体原因或结果（最多1000字）", error_code="WORK_ITEM_REASON_REQUIRED")
    review = payload.get("review_at")
    if isinstance(review, str):
        review = datetime.fromisoformat(review)
    review = to_beijing_naive(review) if review else None
    if operation in {"wait", "block", "snooze", "record_delivery_plan"} and (review is None or review <= beijing_now()):
        raise pcw_errors.bad_request("需要未来的核验时间", error_code="REVIEW_TIME_REQUIRED")
    if operation == "wait" and payload.get("waiting_kind") not in {"customer", "colleague", "source"}:
        raise pcw_errors.bad_request("请选择等待对象", error_code="WAITING_KIND_REQUIRED")
    if operation == "pause" and not str(payload.get("resume_condition") or "").strip():
        raise pcw_errors.bad_request("需要人工恢复条件", error_code="RESUME_CONDITION_REQUIRED")
    evidence = []
    delivery_plan_payload = {}
    if operation == "record_delivery_plan":
        from app.customer.models import CustomerMessage
        from app.customer.work_item_source_service import current_delivery_trigger, observe_dependency

        description = str(payload.get("delivery_plan") or "").strip()
        decision = payload.get("delivery_decision")
        if not description or decision not in {"alternative", "original_schedule"}:
            raise pcw_errors.bad_request("请明确选择的交付方案及方案决定", error_code="DELIVERY_PLAN_REQUIRED")
        evidence = validate_evidence(db, access, payload.get("evidence_refs") or [])
        outbound = [db.get(CustomerMessage, ref["id"]) for ref in evidence if ref["type"] in {"message", "customer_message"}]
        if len(outbound) != 1 or outbound[0].direction != "out":
            raise pcw_errors.conflict("方案决定需要一条已发给客户的真实出站消息", error_code="GOAL_EVIDENCE_MISMATCH")
        source_event = current_delivery_trigger(db, item)
        if source_event is None:
            raise pcw_errors.conflict("原始物流异常事件已变化，请核对来源并另立当前目标",
                                      error_code="SOURCE_REVALIDATION_REQUIRED")
        baseline = to_beijing_naive(source_event.event_time)
        reopened = db.query(WorkItemEvent).filter_by(item_id=item.id,
            event_type="reopen").order_by(WorkItemEvent.id.desc()).first()
        if reopened is not None:
            from app.customer.models import CustomerMessage
            reopened_at = reopened.occurred_at
            for ref in reopened.evidence_refs or []:
                if ref.get("type") in {"message", "customer_message"}:
                    message = db.get(CustomerMessage, ref.get("id"))
                    if message is not None:
                        reopened_at = max(reopened_at, message.sent_at)
            baseline = max(baseline, reopened_at)
        if outbound[0].sent_at < baseline:
            raise pcw_errors.conflict("方案消息早于本次交付异常，不能作为当前方案",
                                      error_code="DELIVERY_PLAN_STALE_MESSAGE")
        if reopened is not None and outbound[0].sent_at <= baseline:
            raise pcw_errors.conflict("重开后需要针对本轮新事实发送并登记新方案",
                                      error_code="DELIVERY_PLAN_STALE_MESSAGE")
        shipments = db.query(WorkItemDependency).filter_by(item_id=item.id,
            source_domain="shipment", required=True).order_by(WorkItemDependency.id).with_for_update().all()
        if not shipments or any(not observe_dependency(db, dep, item,
                actor_user_id=access.actor_user_id)[2] for dep in shipments):
            raise pcw_errors.conflict("交付方案需要有效的订单运单关联来源", error_code="REQUIRED_DEPENDENCY_UNAVAILABLE")
        delivery_plan_payload = {"delivery_plan": description, "delivery_decision": decision,
            "conversation_id": outbound[0].conversation_id, "outbound_message_id": outbound[0].id,
            "shipment_ids": [int(dep.source_id) for dep in shipments]}
    if operation == "reverify":
        evidence = validate_evidence(db, access, payload.get("evidence_refs") or [])
        from app.customer.work_item_source_service import current_delivery_trigger, observe_dependency
        if item.goal_type == "delivery_exception" and current_delivery_trigger(db, item) is None:
            raise pcw_errors.conflict("原异常源事件已变化，请终止旧目标并从当前源事件建新计划",
                                      error_code="SOURCE_REVALIDATION_REQUIRED")
        for dependency in db.query(WorkItemDependency).filter(WorkItemDependency.item_id == item.id,
                WorkItemDependency.required.is_(True)).order_by(WorkItemDependency.id).with_for_update():
            _status, _revision, valid = observe_dependency(db, dependency, item, actor_user_id=access.actor_user_id)
            if not valid:
                stale_action = dependency.source_domain == "action" and db.query(CustomerAction).filter(
                    CustomerAction.id == dependency.source_id, CustomerAction.work_item_id == item.id,
                    CustomerAction.status.in_(("pending", "snoozed")),
                    CustomerAction.evidence_status == "stale").one_or_none()
                if stale_action is None:
                    raise pcw_errors.conflict("必要来源仍不可用", error_code="REQUIRED_DEPENDENCY_UNAVAILABLE")
    if operation in {"resolve", "revalidate"}:
        if item.goal_type == "delivery_exception" and payload.get("customer_decision") != "accepted":
            raise pcw_errors.bad_request("请明确确认客户接受了对应交付方案；拒绝或未确认不能结案",
                                         error_code="CUSTOMER_DECISION_REQUIRED")
        if not item.source_valid and operation != "revalidate":
            raise pcw_errors.conflict("来源已失效，先重新核验", error_code="SOURCE_REVALIDATION_REQUIRED")
        evidence = validate_evidence(db, access, payload.get("evidence_refs") or [], item=item)
        require_dependencies(db, item, actor_user_id=access.actor_user_id)
        pending = db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
            CustomerAction.status.in_(("pending", "snoozed"))).order_by(CustomerAction.id).with_for_update().all()
        if pending and not payload.get("cancel_remaining"):
            raise pcw_errors.conflict("仍有行动未处理，请明确取消剩余行动", error_code="OPEN_ACTIONS_REQUIRE_DECISION")
        for action in pending:
            action.status = "cancelled"
            action.row_version += 1
            action.updated_at = beijing_now()
    if operation == "reopen":
        evidence = validate_evidence(db, access, payload.get("evidence_refs") or [])
        if all(ref in (item.resolution_evidence or []) for ref in evidence):
            raise pcw_errors.conflict("重开需要新事实依据", error_code="REOPEN_NEW_EVIDENCE_REQUIRED")
    previous = item.state
    if item.owner_user_id is None:
        item.owner_user_id = access.actor_user_id
    previous_result = {"summary": item.resolution_summary, "evidence": item.resolution_evidence}
    snapshot = {name: getattr(item, name) for name in ("state", "waiting_kind", "pause_reason", "resume_condition", "paused_state")}
    snapshot["review_at"] = item.review_at.isoformat() if item.review_at else None
    if operation == "pause":
        item.paused_state = previous
        item.state = "paused"
        item.pause_reason = reason
        item.resume_condition = payload["resume_condition"]
        freeze_delegations(db, item, actor=access.actor_user_id, reason=reason)
    elif operation == "resume":
        if not item.source_valid:
            raise pcw_errors.conflict("来源需要核验后才能恢复", error_code="SOURCE_REVALIDATION_REQUIRED")
        item.state = "open"
        item.pause_reason = None
        item.paused_state = None
        if not db.query(CustomerAction.id).filter(CustomerAction.work_item_id == item.id,
                CustomerAction.status.in_(("pending", "snoozed"))).first():
            from app.customer.pcw_workitem_service import create_pcw_action
            create_pcw_action(db, work_item=item, owner_user_id=item.owner_user_id or access.actor_user_id,
                action_type="review", thread_group="key_account", priority="normal", reason=reason,
                next_action="核对恢复条件并确认下一步", channel="internal", planned_at=beijing_now())
        # Continuing a delegation requires a new controlled Run, not reviving a finished Run.
        for delegation in db.query(CustomerDelegation).filter(CustomerDelegation.item_id == item.id,
                CustomerDelegation.status == "paused", CustomerDelegation.pause_origin == "item").order_by(CustomerDelegation.id).with_for_update():
            delegation.status = "blocked"
            delegation.pause_reason = "事项已恢复，请重新核验委派输入后继续"
            delegation.row_version += 1
    elif operation == "reopen":
        item.state = "open"
        item.result_validity = "pending"
        item.resolved_at = None
        item.resolved_by = None
        # A revoked source cannot authorize even an internal action yet. The
        # next explicit reverify creates that review round after live checks.
        if item.source_valid:
            from app.customer.pcw_workitem_service import create_pcw_action
            create_pcw_action(db, work_item=item, owner_user_id=item.owner_user_id or access.actor_user_id,
                action_type="review", thread_group="key_account", priority="normal", reason=reason,
                next_action="根据新事实核验目标并确认下一步", channel="internal", planned_at=beijing_now(),
                evidence_fact_ids=[ref["id"] for ref in evidence if ref["type"] == "fact"],
                source_event_ids=[ref["id"] for ref in evidence if ref["type"] == "event"])
    elif operation == "reverify":
        stale_actions = db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
                CustomerAction.status.in_(("pending", "snoozed")),
                CustomerAction.evidence_status == "stale").order_by(CustomerAction.id).with_for_update().all()
        item.source_valid = True
        superseded = []
        for action in stale_actions:
            action_dependencies = db.query(WorkItemDependency).filter_by(item_id=item.id,
                source_domain="action", source_id=str(action.id)).with_for_update().all()
            needs_replacement = action.required_for_resolution or any(row.required for row in action_dependencies)
            action.status = "cancelled"
            action.dismissal_reason = "source_changed"
            action.row_version += 1
            action.updated_at = beijing_now()
            if not needs_replacement:
                continue
            from app.customer.pcw_workitem_service import create_pcw_action
            replacement = create_pcw_action(db, work_item=item,
                owner_user_id=action.owner_user_id or item.owner_user_id or access.actor_user_id,
                action_type=action.action_type, thread_group=action.thread_group,
                priority=action.priority, reason=reason, next_action=action.next_action,
                channel=action.channel, contact_id=action.contact_id, opportunity_id=action.opportunity_id,
                business_due_at=action.business_due_at, original_due_at=action.original_due_at,
                due_provenance=action.due_provenance, planned_at=beijing_now(),
                evidence_fact_ids=[ref["id"] for ref in evidence if ref["type"] == "fact"],
                source_event_ids=[ref["id"] for ref in evidence if ref["type"] == "event"],
                parent_action=action, source_type="human_reverify",
                allow_paused_replacement=item.state == "paused")
            replacement.required_for_resolution = True
            action.required_for_resolution = False
            for dependency in action_dependencies:
                dependency.source_id = str(replacement.id)
                dependency.observed_status = replacement.status
                dependency.observed_revision = str(replacement.row_version)
                dependency.source_valid = True
                dependency.observed_at = beijing_now()
            superseded.append({"old_action_id": action.id, "replacement_action_id": replacement.id,
                "required_for_resolution": True})
        if item.state != "paused":
            item.state = "open"
            item.review_at = beijing_now()
        if item.state != "paused" and not superseded:
            from app.customer.pcw_workitem_service import create_pcw_action
            create_pcw_action(db, work_item=item, owner_user_id=item.owner_user_id or access.actor_user_id,
                action_type="review", thread_group="key_account", priority="normal", reason=reason,
                next_action="复核更新后的事实并确认下一步", channel="internal", planned_at=beijing_now(),
                evidence_fact_ids=[ref["id"] for ref in evidence if ref["type"] == "fact"],
                source_event_ids=[ref["id"] for ref in evidence if ref["type"] == "event"])
    elif operation in {"resolve", "revalidate"}:
        item.state = "resolved"
        item.result_validity = "verified"
        item.source_valid = True
        item.resolution_summary = reason
        item.resolution_evidence = evidence
        item.resolved_at = beijing_now()
        item.resolved_by = access.actor_user_id
        freeze_delegations(db, item, terminal=True, actor=access.actor_user_id, reason=reason)
    elif operation == "cancel":
        item.state = "cancelled"
        item.resolution_summary = reason
        freeze_delegations(db, item, terminal=True, actor=access.actor_user_id, reason=reason)
        for action in db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
                CustomerAction.status.in_(("pending", "snoozed"))).order_by(CustomerAction.id).with_for_update():
            action.status = "cancelled"
            action.row_version += 1
            action.updated_at = beijing_now()
    elif operation == "snooze":
        item.review_at = review
    elif operation == "record_delivery_plan":
        item.state = "waiting"
        item.waiting_kind = "customer"
        item.review_at = review
        item.resume_condition = "等待客户对已发送交付方案的回复，并核验源模块履约结果"
    else:
        item.state = {"start": "in_progress", "wait": "waiting", "decide": "decision_required", "block": "blocked"}[operation]
        item.review_at = review
        item.waiting_kind = payload.get("waiting_kind") if operation == "wait" else None
        item.resume_condition = reason
    event = record_event(db, item, actor=access.actor_user_id,
        operation="delivery_plan_decided" if operation == "record_delivery_plan" else operation, previous=previous,
        reason=reason, evidence=evidence, payload={"before": snapshot, "previous_result": previous_result,
            "superseded_required_actions": superseded if operation == "reverify" else [],
            **delivery_plan_payload,
            **({"customer_decision": payload["customer_decision"]} if item.goal_type == "delivery_exception"
                and operation in {"resolve", "revalidate"} else {})})
    return event


def transition_item(db, user, item_id, payload, idempotency_key):
    item, access = item_access(db, user, item_id, write=True, lock=True)

    def execute():
        from app.customer.work_item_query_service import serialize_item
        event = apply_transition(db, item, access, payload)
        return {"item": serialize_item(db, user, item, access), "event_id": event.id}

    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id,
        operation_scope=f"work_item_transition:{item_id}", idempotency_key=idempotency_key,
        request_payload=payload, execute=execute)
    return result
