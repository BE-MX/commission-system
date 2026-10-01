"""Deterministic source observations; never accept client completion claims."""

from app.core.time import beijing_now
from app.customer.models import CustomerAction, CustomerOrder
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.work_item_evidence_service import evidence_revision


def current_delivery_trigger(db, item):
    """Return the persisted anomaly event only while its registered source revision is intact."""
    from app.customer.pcw_models import MaintenancePlan
    from app.tracking.models import TrackingEvent

    context = item.context_json or {}
    plan = db.get(MaintenancePlan, context.get("plan_id")) if context.get("plan_id") else None
    event = db.get(TrackingEvent, context.get("shipment_event_id")) if context.get("shipment_event_id") else None
    refs = (plan.evidence_json or {}).get("refs", []) if plan else []
    expected = next((ref.get("revision") for ref in refs if ref.get("type") == "tracking_event"
        and ref.get("id") == context.get("shipment_event_id")), None)
    return event if plan and plan.plan_type == "shipping" and event and expected == evidence_revision(event) else None


def observe_dependency(db, dependency, item, *, actor_user_id=None):
    from app.auth.service import get_live_user_authorization
    roles, permissions = get_live_user_authorization(db, actor_user_id or item.owner_user_id) if actor_user_id or item.owner_user_id else ([], [])
    perms = set(permissions)
    admin = "super_admin" in roles
    logical_id = db.query(logical_owner_expression(type(item), "work_item")).filter(type(item).id == item.id).scalar()
    if dependency.source_domain == "action":
        row = db.query(CustomerAction).filter(CustomerAction.id == dependency.source_id,
            CustomerAction.work_item_id == item.id,
            logical_owner_expression(CustomerAction, "action") == logical_id).one_or_none()
        if row is not None:
            return row.status, str(row.row_version), row.evidence_status == "valid"
    elif dependency.source_domain == "shipment":
        if not admin and not perms.intersection({"tracking:read", "tracking:write"}):
            return "permission_unavailable", None, False
        from app.customer.pcw_models import ShipmentOrderLink
        from app.tracking.models import ShipmentTracking
        row = db.query(ShipmentTracking).join(ShipmentOrderLink,
            ShipmentOrderLink.shipment_id == ShipmentTracking.id).join(CustomerOrder,
            CustomerOrder.id == ShipmentOrderLink.order_id).filter(
            ShipmentTracking.id == dependency.source_id, ShipmentTracking.deleted_at.is_(None),
            ShipmentOrderLink.state == "active",
            logical_owner_expression(CustomerOrder, "order") == logical_id).one_or_none()
        if row is not None:
            return "delivered" if row.delivered_at else row.unified_status or "unknown", evidence_revision(row), True
    elif dependency.source_domain == "design":
        if not admin and not perms.intersection({"design:read", "design:write", "design:manage", "design:audit"}):
            return "permission_unavailable", None, False
        from app.design.models import DesignScheduleTask, DesignScheduleRequest
        from app.customer.models import CustomerExternalIdentity
        row = db.query(DesignScheduleTask).join(DesignScheduleRequest,
            DesignScheduleRequest.id == DesignScheduleTask.request_id).filter(DesignScheduleTask.id == dependency.source_id,
            DesignScheduleRequest.deleted_at.is_(None)).one_or_none()
        if row is not None and row.customer_id:
            identities = db.query(logical_owner_expression(CustomerExternalIdentity, "external_identity")).filter(
                CustomerExternalIdentity.source_system == "okki", CustomerExternalIdentity.identifier_type == "company_id",
                CustomerExternalIdentity.normalized_value == row.customer_id, CustomerExternalIdentity.status == "active",
                CustomerExternalIdentity.verification_status == "verified", CustomerExternalIdentity.identity_strength == "strong",
                CustomerExternalIdentity.cardinality == "one_to_one").distinct().all()
            if {identity[0] for identity in identities} == {logical_id}:
                return row.status, evidence_revision(row), row.status != "cancelled"
    return "unknown", None, False


def attach_dependency(db, user, item_id, payload, idempotency_key):
    from app.customer.work_item_service import item_access, record_event
    from app.customer.pcw_workitem_service import _require_version
    from app.customer.workbench_models import WorkItemDependency
    from app.customer.pcw_idempotency import run_with_receipt
    from app.customer import pcw_errors
    item, access = item_access(db, user, item_id, write=True, lock=True)
    def execute():
        _require_version(item.row_version, payload["expected_item_version"], "WORK_ITEM_VERSION_CONFLICT", "current_item_version")
        if item.state in {"resolved", "cancelled", "paused"}:
            raise pcw_errors.conflict("当前状态不可新增执行依赖", error_code="WORK_ITEM_TRANSITION_INVALID")
        row = db.query(WorkItemDependency).filter_by(item_id=item.id, source_domain=payload["source_domain"], source_id=str(payload["source_id"])).with_for_update().one_or_none()
        if row is None:
            row = WorkItemDependency(item_id=item.id, source_domain=payload["source_domain"], source_id=str(payload["source_id"]), title=payload["title"], required=payload["required"])
        status, revision, valid = observe_dependency(db, row, item, actor_user_id=access.actor_user_id)
        if not valid:
            raise pcw_errors.not_found("源任务未关联该客户或无查看权限", error_code="DEPENDENCY_SOURCE_NOT_FOUND")
        row.observed_status, row.observed_revision, row.source_valid, row.observed_at = status, revision, valid, beijing_now()
        db.add(row)
        record_event(db, item, actor=access.actor_user_id, operation="dependency_linked", previous=item.state,
            reason=payload["reason"], payload={"source_domain": row.source_domain, "source_id": row.source_id, "source_revision": revision})
        return {"dependency_id": row.id, "item_version": item.row_version, "status": status}
    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id, operation_scope=f"work_item_dependency:{item_id}", idempotency_key=idempotency_key,
        request_payload=payload, execute=execute)
    return result


def refresh_dependency(db, dependency, item):
    status, revision, valid = observe_dependency(db, dependency, item)
    dependency.observed_status = status
    dependency.observed_revision = revision
    dependency.source_valid = valid
    dependency.observed_at = beijing_now()
    return dependency


def reconcile_item_inputs(db, item, *, read_only=False, actor_user_id=None):
    """Read current sources, never apply a notification's stale snapshot to business state.

    Sources without an outbox are reconciled with a persisted per-item delivery watermark.
    Read/write/tool boundaries also call this function, so a revoked result cannot remain current.
    """
    from app.auth.service import get_live_user_authorization
    from app.customer import pcw_errors
    from app.customer.access_service import require_customer_access, CustomerAccessDenied
    from app.customer.models import CustomerFact, CustomerMessage, CustomerEvent
    from app.customer.pcw_models import CustomerWorkItem
    from app.customer.workbench_models import WorkItemDependency, WorkItemSourceDelivery, CustomerDelegation
    from app.customer.work_item_evidence_service import validate_evidence
    from app.customer.work_item_service import record_event, freeze_delegations, READ
    from app.customer.workflow_service import _account_for_update
    logical_id = db.query(logical_owner_expression(CustomerWorkItem, "work_item")).filter(CustomerWorkItem.id == item.id).scalar()
    if not read_only:
        _account_for_update(db, logical_id)
    item_query = db.query(CustomerWorkItem).filter(CustomerWorkItem.id == item.id).populate_existing()
    item = (item_query.one() if read_only else item_query.with_for_update().one())
    from app.customer.work_item_service import reconcile_assignment
    reconcile_assignment(db, item, logical_id, read_only=read_only)
    actor = actor_user_id or item.owner_user_id or item.resolved_by
    if actor is None:
        from app.customer.models import CustomerAssignment
        actor = db.query(CustomerAssignment.user_id).filter(CustomerAssignment.customer_id == logical_id,
            CustomerAssignment.assignment_role == "primary", CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None)).scalar()
    roles, permissions = get_live_user_authorization(db, actor) if actor else ([], [])
    try:
        access = require_customer_access(db, customer_id=logical_id, user={"sub": actor or 0,
            "roles": roles, "permissions": permissions}, action_permissions=READ, manage_permissions=("customer:admin",))
    except CustomerAccessDenied:
        # Assignment/permission loss is checked independently at every execution boundary.
        if read_only:
            raise pcw_errors.conflict("来源查看权限已变化，请停止当前委派", error_code="SOURCE_ACCESS_REVOKED")
        return item
    changes, invalid = [], False
    # Reopen preserves old result evidence for history, but it is no longer the
    # current goal's acceptance source and must not fence a new review cycle.
    for ref in (item.resolution_evidence or []) if item.state == "resolved" else []:
        kind = ref.get("type")
        model = {"fact": CustomerFact, "message": CustomerMessage, "customer_message": CustomerMessage, "event": CustomerEvent}.get(kind)
        row = db.get(model, ref.get("id")) if model else None
        current = evidence_revision(row) if row else "missing"
        try:
            validate_evidence(db, access, [ref])
        except pcw_errors.PcwError:
            invalid = True
            changes.append((kind or "unknown", str(ref.get("id")), current, "result_evidence_changed"))
    if item.goal_type == "delivery_exception":
        from app.customer.workbench_models import WorkItemEvent

        if current_delivery_trigger(db, item) is None:
            invalid = True
            changes.append(("tracking_event", str((item.context_json or {}).get("shipment_event_id") or "missing"),
                "unavailable", "delivery_trigger_changed"))
        plan_event = db.query(WorkItemEvent).filter_by(item_id=item.id,
            event_type="delivery_plan_decided").order_by(WorkItemEvent.id.desc()).first()
        reopened = db.query(WorkItemEvent.id).filter_by(item_id=item.id,
            event_type="reopen").order_by(WorkItemEvent.id.desc()).first()
        current_plan = plan_event if plan_event and (not reopened or plan_event.id > reopened.id) else None
        for ref in (current_plan.evidence_refs or []) if current_plan else []:
            model = {"fact": CustomerFact, "message": CustomerMessage,
                "customer_message": CustomerMessage, "event": CustomerEvent}.get(ref.get("type"))
            row = db.get(model, ref.get("id")) if model else None
            try:
                validate_evidence(db, access, [ref])
            except pcw_errors.PcwError:
                invalid = invalid or item.state == "resolved"
                changes.append((ref.get("type") or "unknown", str(ref.get("id")),
                    evidence_revision(row) if row else "missing", "delivery_plan_source_changed"))
    action_query = db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
        CustomerAction.status.in_(("pending", "snoozed"))).order_by(CustomerAction.id)
    actions = (action_query.all() if read_only else action_query.with_for_update().all())
    from app.customer.evidence_service import visible_facts, serialize_facts
    for action in actions:
        facts = visible_facts(db, access).filter(CustomerFact.id.in_(action.evidence_fact_ids or [])).all()
        valid_ids = {row["id"] for row in serialize_facts(db, facts) if row["selectable"]}
        from app.customer.evidence_service import visible_events
        events = visible_events(db, access).filter(CustomerEvent.id.in_(action.source_event_ids or [])).all()
        current_revisions = {
            "fact": {str(row.id): evidence_revision(row) for row in facts if row.id in valid_ids},
            "event": {str(row.id): evidence_revision(row) for row in events},
        }
        recorded_revisions = (action.feedback_json or {}).get("source_revisions")
        changed = (set(action.evidence_fact_ids or []) != valid_ids
            or {row.id for row in events} != set(action.source_event_ids or [])
            or (bool(action.evidence_fact_ids or action.source_event_ids)
                and recorded_revisions != current_revisions))
        if changed:
            invalid = True
            if not read_only:
                action.evidence_status = "stale"
            from app.customer.pcw_idempotency import canonical_request_hash
            changes.append(("action", str(action.id), canonical_request_hash(current_revisions), "action_evidence_changed"))
    dependency_query = db.query(WorkItemDependency).filter(WorkItemDependency.item_id == item.id).order_by(WorkItemDependency.id)
    dependencies = dependency_query.all() if read_only else dependency_query.with_for_update().all()
    for dependency in dependencies:
        status, revision, valid = observe_dependency(db, dependency, item, actor_user_id=actor)
        if dependency.observed_revision is not None and (dependency.observed_revision != revision or dependency.source_valid != valid):
            changes.append((dependency.source_domain, dependency.source_id, revision or "unavailable", "dependency_changed"))
        required_result_withdrawn = (dependency.required and item.state == "resolved"
            and status not in {"done", "completed", "fulfilled", "delivered"})
        if dependency.required and (not valid or required_result_withdrawn):
            invalid = True
            changes.append((dependency.source_domain, dependency.source_id, revision or "unavailable",
                "dependency_result_withdrawn" if required_result_withdrawn and valid else "dependency_unavailable"))
        if not read_only:
            dependency.observed_status, dependency.observed_revision = status, revision
            dependency.source_valid, dependency.observed_at = valid, beijing_now()
    if read_only:
        if changes or invalid:
            raise pcw_errors.conflict("事项来源已变化，请重新核验后继续", error_code="SOURCE_INPUT_CHANGED")
        return item
    fresh_changes = []
    from app.customer.pcw_idempotency import canonical_request_hash
    for domain, identity, revision, reason in changes:
        event_id = f"{domain}:{identity}:{canonical_request_hash({'revision': revision, 'reason': reason})[:24]}"[:64]
        exists = db.query(WorkItemSourceDelivery.id).filter_by(item_id=item.id, source_domain=domain,
            source_event_id=event_id, source_revision=1).first()
        if exists is None:
            db.add(WorkItemSourceDelivery(item_id=item.id, source_domain=domain, source_event_id=event_id, source_revision=1))
            fresh_changes.append({"domain": domain, "id": identity, "revision": revision, "reason": reason})
    if fresh_changes:
        previous = item.state
        item.source_revision += 1
        if invalid:
            item.source_valid = False
            if item.state == "resolved":
                item.result_validity = "review_required"
            elif item.state not in {"paused", "cancelled"}:
                item.state = "blocked"
                item.resume_condition = "来源发生变化，请核验当前事实后人工决定下一步"
            freeze_delegations(db, item, reason="来源或必要依赖发生变化")
            for delegation in db.query(CustomerDelegation).filter(CustomerDelegation.item_id == item.id,
                    CustomerDelegation.status == "paused", CustomerDelegation.pause_origin == "item"):
                delegation.status = "blocked"
                delegation.pause_origin = "source"
        record_event(db, item, actor=None, operation="source_invalidated" if invalid else "source_updated",
            previous=previous, reason="核验发现当前来源变化；保留旧执行与结果历史", payload={"changes": fresh_changes})
    return item


def reconcile_sources_job():
    import logging
    from app.core.database import SessionLocal
    from app.customer.pcw_models import CustomerWorkItem
    from app.customer.workbench_models import WorkbenchDailyPlan
    with SessionLocal() as db:
        ids = [row[0] for row in db.query(CustomerWorkItem.id).filter(CustomerWorkItem.state != "cancelled").order_by(CustomerWorkItem.id)]
        for identity in ids:
            try:
                with db.begin_nested():
                    reconcile_item_inputs(db, db.get(CustomerWorkItem, identity))
                db.commit()
            except Exception as exc:
                db.rollback()
                logging.getLogger(__name__).error("Work item source reconciliation failed item=%s error=%s", identity, type(exc).__name__)
                print(f"Work item source reconciliation failed item={identity} error={type(exc).__name__}", flush=True)
