"""A delivery exception needs a chosen plan, customer response and source fulfillment."""

from datetime import timedelta

import pytest

from app.core.time import beijing_now, beijing_today
from app.customer import pcw_errors
from app.customer.pcw_maintenance_service import create_plan, create_shipment_order_link
from app.customer.pcw_workitem_service import complete_action_v2
from app.customer.pcw_models import CustomerWorkItem, ShipmentOrderLink
from app.customer.work_item_evidence_service import evidence_revision
from app.customer.work_item_service import transition_item
from app.customer.workbench_models import WorkItemDependency, WorkItemEvent
from app.tracking.models import ShipmentTracking, TrackingEvent
from tests.test_customer_workbench_lifecycle import _actor
from tests.test_customer_workflow import _grant_permission
from tests.test_pcw_evaluation import _conversation, _message
from tests.test_pcw_maintenance import _order, _setup


def _exception(db, *, shipment_status="exception", newer_event=False):
    account, owner = _setup(db, code="C-DELIVERY-EXCEPTION", user_id=9471)
    _grant_permission(db, owner.id, "tracking:read")
    order = _order(db, account, seq=9471, order_date=beijing_today())
    now = beijing_now().replace(microsecond=0)
    shipment = ShipmentTracking(waybill_no="WB-EXCEPTION-9471", carrier="DHL", carrier_name="DHL",
        current_status=shipment_status, unified_status=shipment_status, dingtalk_user_id="dt-9471",
        dingtalk_user_name="tester", created_at=now, updated_at=now)
    db.add(shipment)
    db.flush()
    linked = create_shipment_order_link(db, actor_user_id=owner.id, shipment_id=shipment.id,
        order_id=order.id, evidence_refs=[{"type": "manual", "id": 9471}])
    event = TrackingEvent(waybill_no=shipment.waybill_no, carrier=shipment.carrier,
        event_time=now, status_code="NU", description="Delivery exception", synced_at=now)
    db.add(event)
    db.flush()
    if newer_event:
        db.add(TrackingEvent(waybill_no=shipment.waybill_no, carrier=shipment.carrier,
            event_time=now + timedelta(minutes=1), status_code="NU", description="Latest exception",
            synced_at=now + timedelta(minutes=1)))
        db.flush()
    plan = create_plan(db, customer_id=account.id, actor_user_id=owner.id, plan_type="shipping",
        title="Agree a safe delivery alternative", typed_payload={"shipment_order_link_ids": [linked["link_id"]],
        "trigger_event_type": "NU", "shipment_event_id": event.id, "contact_channel": "email"},
        evidence_refs=[{"type": "tracking_event", "id": event.id, "revision": evidence_revision(event)}])
    item = db.get(CustomerWorkItem, plan["occurrence"]["work_item_id"])
    user = {**_actor(owner), "permissions": [*_actor(owner)["permissions"], "tracking:read"]}
    return account, owner, user, item, shipment


def _ref(row):
    return {"type": "message", "id": row.id, "revision": evidence_revision(row)}


def test_routine_shipping_contact_does_not_become_delivery_exception(db):
    _account, _owner, _user, item, _shipment = _exception(db, shipment_status="in_transit")
    assert item.goal_type == "maintenance"
    assert db.query(WorkItemDependency).filter_by(item_id=item.id).count() == 0


def test_old_shipping_event_does_not_become_current_exception_goal(db):
    _account, _owner, _user, item, _shipment = _exception(db, newer_event=True)
    assert item.goal_type == "maintenance"
    assert db.query(WorkItemDependency).filter_by(item_id=item.id).count() == 0


def test_retracted_exception_event_blocks_the_old_goal(db):
    account, _owner, user, item, _shipment = _exception(db)
    trigger = db.get(TrackingEvent, item.context_json["shipment_event_id"])
    trigger.description = "Carrier corrected this scan"
    db.flush()
    from app.customer.work_item_source_service import reconcile_item_inputs
    reconcile_item_inputs(db, item)
    assert item.state == "blocked" and not item.source_valid
    conv = _conversation(db, account, external_id="corrected-scan")
    message = _message(db, account, conv, external_id="new-context", direction="in",
        sent_at=beijing_now(), record_id=99482)
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, user, item.id, {"operation": "reverify", "expected_item_version": item.row_version,
            "reason": "Trying the revoked scan", "evidence_refs": [_ref(message)]}, "reverify-revoked-trigger-001")
    assert caught.value.error_code == "SOURCE_REVALIDATION_REQUIRED"


def test_exception_requires_recorded_plan_response_and_delivered_source(db):
    account, owner, user, item, shipment = _exception(db)
    assert item.goal_type == "delivery_exception"
    assert {row.source_id for row in db.query(WorkItemDependency).filter_by(item_id=item.id)} == {str(shipment.id)}
    conv = _conversation(db, account, external_id="delivery-response")
    outbound = _message(db, account, conv, external_id="proposed-plan", direction="out",
        sent_at=beijing_now() + timedelta(seconds=1), record_id=99471)
    inbound = _message(db, account, conv, external_id="accepted-plan", direction="in",
        sent_at=beijing_now() + timedelta(seconds=2), record_id=99472)
    from app.customer.models import CustomerAction
    action = db.query(CustomerAction).filter_by(work_item_id=item.id).one()
    with pytest.raises(pcw_errors.PcwError) as caught:
        complete_action_v2(db, action_id=action.id, actor_user_id=owner.id,
            expected_action_version=action.row_version, expected_work_item_version=item.row_version,
            expected_occurrence_version=1, work_item_transition="resolve", outcome_code="replied",
            channel="email", occurred_at=beijing_now(), summary="Claimed acceptance",
            evidence_message_ids=[inbound.id], idempotency_key="delivery-old-resolve-001")
    assert caught.value.error_code == "GOAL_REQUIRES_ITEM_TRANSITION"
    with pytest.raises(pcw_errors.PcwError):
        transition_item(db, user, item.id, {"operation": "resolve", "expected_item_version": item.row_version,
            "reason": "Customer accepted", "customer_decision": "accepted",
            "evidence_refs": [_ref(inbound)], "cancel_remaining": True}, "delivery-too-soon")
    transition_item(db, user, item.id, {"operation": "record_delivery_plan", "expected_item_version": item.row_version,
        "reason": "We can split delivery without changing the customer price", "delivery_decision": "alternative",
        "delivery_plan": "Dispatch available stock first and confirm the rest separately",
        "evidence_refs": [_ref(outbound)], "review_at": (beijing_now() + timedelta(days=1)).isoformat()}, "delivery-plan-0001")
    assert db.query(WorkItemEvent).filter_by(item_id=item.id, event_type="delivery_plan_decided").count() == 1
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, user, item.id, {"operation": "resolve", "expected_item_version": item.row_version,
            "reason": "Customer accepted", "customer_decision": "accepted",
            "evidence_refs": [_ref(inbound)], "cancel_remaining": True}, "delivery-before-fulfillment")
    assert caught.value.error_code == "REQUIRED_DEPENDENCY_OPEN"
    shipment.delivered_at = beijing_now()
    shipment.unified_status = "delivered"
    db.flush()
    from app.customer.work_item_source_service import reconcile_item_inputs
    reconcile_item_inputs(db, item)
    # The sales contact action is separately recorded; the source shipment alone
    # cannot claim this outcome for the customer.
    for action in db.query(CustomerAction).filter_by(work_item_id=item.id):
        action.status = "done"
    db.flush()
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, user, item.id, {"operation": "resolve", "expected_item_version": item.row_version,
            "reason": "Unconfirmed answer", "evidence_refs": [_ref(inbound)]}, "delivery-no-acceptance")
    assert caught.value.error_code == "CUSTOMER_DECISION_REQUIRED"
    transition_item(db, user, item.id, {"operation": "resolve", "expected_item_version": item.row_version,
        "reason": "Accepted alternative fulfilled and delivery confirmed", "customer_decision": "accepted",
        "evidence_refs": [_ref(inbound)],
        "cancel_remaining": True}, "delivery-resolved")
    assert item.state == "resolved"
    assert item.result_validity == "verified"
    from app.customer.work_item_query_service import get_item
    history = get_item(db, user, item.id)["history"]
    assert next(row for row in history if row["event_type"] == "delivery_plan_decided")["delivery_plan"] == (
        "Dispatch available stock first and confirm the rest separately")
    assert next(row for row in history if row["event_type"] == "resolve")["customer_decision"] == "accepted"
    outbound.content_hash = "d" * 64
    inbound.content_hash = "c" * 64
    db.flush()
    reconcile_item_inputs(db, item)
    assert item.result_validity == "review_required"
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, user, item.id, {"operation": "revalidate",
            "expected_item_version": item.row_version, "reason": "Old plan cannot be revalidated",
            "customer_decision": "accepted", "evidence_refs": [_ref(inbound)]}, "delivery-old-plan-review-001")
    assert caught.value.error_code == "DELIVERY_PLAN_SOURCE_CHANGED"
    new_fact = _message(db, account, conv, external_id="new-objection", direction="in",
        sent_at=beijing_now() + timedelta(minutes=1), record_id=99476)
    transition_item(db, user, item.id, {"operation": "reopen", "expected_item_version": item.row_version,
        "reason": "Previous proposal was corrected", "evidence_refs": [_ref(new_fact)]}, "delivery-reopen-001")
    assert item.state == "open" and not item.source_valid
    transition_item(db, user, item.id, {"operation": "reverify", "expected_item_version": item.row_version,
        "reason": "Current exception and shipment checked", "evidence_refs": [_ref(new_fact)]}, "delivery-reverify-001")
    assert item.source_valid
    assert reconcile_item_inputs(db, item, read_only=True, actor_user_id=int(user["sub"])).id == item.id
    current_plan = _message(db, account, conv, external_id="corrected-proposal", direction="out",
        sent_at=beijing_now() + timedelta(minutes=2), record_id=99477)
    transition_item(db, user, item.id, {"operation": "record_delivery_plan", "expected_item_version": item.row_version,
        "reason": "Corrected alternative has been sent", "delivery_decision": "alternative",
        "delivery_plan": "Confirm the corrected split delivery", "evidence_refs": [_ref(current_plan)],
        "review_at": (beijing_now() + timedelta(days=1)).isoformat()}, "delivery-new-plan-001")
    assert db.query(WorkItemEvent).filter_by(item_id=item.id, event_type="delivery_plan_decided").count() == 2


def test_unrelated_or_older_message_cannot_accept_delivery_plan(db):
    account, owner, user, item, shipment = _exception(db)
    conv = _conversation(db, account, external_id="plan-conversation")
    older = _message(db, account, conv, external_id="older-answer", direction="in",
        sent_at=beijing_now() - timedelta(days=1), record_id=99473)
    outbound = _message(db, account, conv, external_id="new-plan", direction="out",
        sent_at=beijing_now(), record_id=99474)
    other_conv = _conversation(db, account, external_id="unrelated-conversation")
    unrelated = _message(db, account, other_conv, external_id="other-inquiry", direction="in",
        sent_at=beijing_now() + timedelta(seconds=2), record_id=99475)
    transition_item(db, user, item.id, {"operation": "record_delivery_plan", "expected_item_version": item.row_version,
        "reason": "Customer contacted", "delivery_decision": "alternative", "delivery_plan": "Use verified carrier route",
        "evidence_refs": [_ref(outbound)], "review_at": (beijing_now() + timedelta(days=1)).isoformat()}, "delivery-plan-0002")
    shipment.delivered_at = beijing_now()
    shipment.unified_status = "delivered"
    db.flush()
    from app.customer.work_item_source_service import reconcile_item_inputs
    reconcile_item_inputs(db, item)
    from app.customer.models import CustomerAction
    for action in db.query(CustomerAction).filter_by(work_item_id=item.id):
        action.status = "done"
    db.flush()
    for message in (older, unrelated):
        with pytest.raises(pcw_errors.PcwError) as caught:
            transition_item(db, user, item.id, {"operation": "resolve", "expected_item_version": item.row_version,
                "reason": "Claimed acceptance", "customer_decision": "accepted",
                "evidence_refs": [_ref(message)]}, f"bad-delivery-message-{message.id}")
        assert caught.value.error_code == "GOAL_EVIDENCE_MISMATCH"


def test_historical_message_before_exception_cannot_become_new_plan(db):
    account, _owner, user, item, _shipment = _exception(db)
    conv = _conversation(db, account, external_id="historic-plan")
    historical = _message(db, account, conv, external_id="three-days-earlier", direction="out",
        sent_at=beijing_now() - timedelta(days=3), record_id=99478)
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, user, item.id, {"operation": "record_delivery_plan",
            "expected_item_version": item.row_version, "reason": "Reused old plan",
            "delivery_decision": "alternative", "delivery_plan": "Historical offer",
            "evidence_refs": [_ref(historical)],
            "review_at": (beijing_now() + timedelta(days=1)).isoformat()}, "delivery-historic-plan-001")
    assert caught.value.error_code == "DELIVERY_PLAN_STALE_MESSAGE"


def test_reopened_exception_needs_a_new_plan_decision(db):
    account, _owner, user, item, shipment = _exception(db)
    conv = _conversation(db, account, external_id="reopened-delivery")
    outbound = _message(db, account, conv, external_id="first-plan", direction="out",
        sent_at=beijing_now() + timedelta(seconds=1), record_id=99479)
    accepted = _message(db, account, conv, external_id="first-accept", direction="in",
        sent_at=beijing_now() + timedelta(seconds=2), record_id=99480)
    transition_item(db, user, item.id, {"operation": "record_delivery_plan",
        "expected_item_version": item.row_version, "reason": "First plan sent", "delivery_decision": "alternative",
        "delivery_plan": "Ship this batch", "evidence_refs": [_ref(outbound)],
        "review_at": (beijing_now() + timedelta(days=1)).isoformat()}, "delivery-first-plan-001")
    shipment.delivered_at = beijing_now()
    shipment.unified_status = "delivered"
    db.flush()
    from app.customer.work_item_source_service import reconcile_item_inputs
    reconcile_item_inputs(db, item)
    from app.customer.models import CustomerAction
    for action in db.query(CustomerAction).filter_by(work_item_id=item.id):
        action.status = "done"
    db.flush()
    transition_item(db, user, item.id, {"operation": "resolve", "expected_item_version": item.row_version,
        "reason": "First issue resolved", "customer_decision": "accepted", "evidence_refs": [_ref(accepted)]},
        "delivery-first-resolve-001")
    later = _message(db, account, conv, external_id="new-issue", direction="in",
        sent_at=beijing_now() + timedelta(minutes=1), record_id=99481)
    transition_item(db, user, item.id, {"operation": "reopen", "expected_item_version": item.row_version,
        "reason": "New customer objection", "evidence_refs": [_ref(later)]}, "delivery-new-cycle-001")
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, user, item.id, {"operation": "record_delivery_plan",
            "expected_item_version": item.row_version, "reason": "Reusing first proposal",
            "delivery_decision": "alternative", "delivery_plan": "Same old batch",
            "evidence_refs": [_ref(outbound)],
            "review_at": (beijing_now() + timedelta(days=1)).isoformat()}, "delivery-reused-outbound-001")
    assert caught.value.error_code == "DELIVERY_PLAN_STALE_MESSAGE"
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, user, item.id, {"operation": "resolve", "expected_item_version": item.row_version,
            "reason": "Reused old plan", "customer_decision": "accepted", "evidence_refs": [_ref(later)],
            "cancel_remaining": True}, "delivery-reused-plan-001")
    assert caught.value.error_code == "GOAL_EVIDENCE_MISMATCH"
