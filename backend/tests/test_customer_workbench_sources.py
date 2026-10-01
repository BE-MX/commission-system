"""Real source changes, authority loss and source completion acceptance."""

from datetime import timedelta
import pytest
from app.core.time import beijing_now
from app.customer.work_item_service import transition_item
from app.customer.work_item_evidence_service import evidence_revision
from app.customer.workbench_models import WorkItemEvent, WorkItemSourceDelivery
from tests.test_customer_workbench_lifecycle import _actor, _customer_with_profile, _open_item, _action
from tests.test_pcw_evaluation import _conversation, _message


def resolved_inquiry(db):
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    conv = _conversation(db, account, external_id="withdrawal-case")
    message = _message(db, account, conv, external_id="answer", direction="out", sent_at=beijing_now(), record_id=98671)
    item.context_json = {"conversation_id": conv.id}
    transition_item(db, _actor(owner), item.id, {"operation": "resolve", "expected_item_version": 1,
        "reason": "Answered customer", "evidence_refs": [{"type": "message", "id": message.id, "revision": evidence_revision(message)}]}, "resolve-source-001")
    return account, owner, item, message


def test_real_result_source_change_requires_review_without_deleting_result(db):
    from app.customer.work_item_source_service import reconcile_item_inputs
    account, owner, item, message = resolved_inquiry(db)
    old_result = list(item.resolution_evidence)
    message.content_text = "Corrected source: delivery promise was not confirmed"
    message.content_hash = "f" * 64
    db.flush()
    reconcile_item_inputs(db, item)
    assert item.state == "resolved"
    assert item.result_validity == "review_required"
    assert item.resolution_evidence == old_result
    assert item.source_revision == 2
    reconcile_item_inputs(db, item)
    assert item.source_revision == 2
    assert db.query(WorkItemEvent).filter_by(item_id=item.id, event_type="source_invalidated").count() == 1
    assert db.query(WorkItemSourceDelivery).filter_by(item_id=item.id).count() == 1


def test_evidence_picker_lists_authorized_real_messages_with_revision(db):
    from app.customer.evidence_service import list_evidence

    account, owner, item, message = resolved_inquiry(db)
    from tests.test_customer_workflow import _account
    other, _profile = _account(db, code="C-PRIVATE-MESSAGE")
    other_conv = _conversation(db, other, external_id="private-other-customer")
    other_message = _message(db, other, other_conv, external_id="private-other-message",
        direction="out", sent_at=beijing_now(), record_id=98674)
    listed = list_evidence(db, _actor(owner), account.id, kind="message")
    assert listed["total"] == 1
    assert listed["items"][0]["evidence_ref"] == {
        "type": "message", "id": message.id, "revision": evidence_revision(message)}
    assert all(row["id"] != other_message.id for row in listed["items"])


def test_message_evidence_rechecks_disabled_user_before_disclosing_text(db):
    from app.customer.evidence_service import list_evidence
    from app.customer.access_service import CustomerAccessDenied

    account, owner, _item, _message_row = resolved_inquiry(db)
    stale_token = _actor(owner)
    owner.is_active = False
    db.flush()
    with pytest.raises(CustomerAccessDenied):
        list_evidence(db, stale_token, account.id, kind="message")


def test_evidence_revision_uses_persisted_datetime_precision(db, monkeypatch):
    from sqlalchemy import update
    from app.customer.models import CustomerMessage

    account, _owner = _customer_with_profile(db)
    conv = _conversation(db, account, external_id="precision-case")
    sent_at = beijing_now().replace(microsecond=600001)
    message = _message(db, account, conv, external_id="precision-msg", direction="out",
        sent_at=sent_at, record_id=98676)
    stored = sent_at.replace(microsecond=0)
    db.execute(update(CustomerMessage).where(CustomerMessage.id == message.id).values(
        sent_at=stored).execution_options(synchronize_session=False))
    # Simulate MySQL DATETIME(0) returning seconds while the identity map still
    # holds the pre-roundtrip Python value. The test DB itself remains SQLite.
    monkeypatch.setattr(db.get_bind().dialect, "name", "mysql")
    revision = evidence_revision(message)
    assert message.sent_at == stored
    assert revision == evidence_revision(message)


def test_delivery_exception_cannot_resolve_from_unrelated_inbound_message(db):
    from app.customer import pcw_errors

    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    item.goal_type = "delivery_exception"
    conv = _conversation(db, account, external_id="unrelated-delivery-chat")
    inbound = _message(db, account, conv, external_id="new-question", direction="in",
        sent_at=beijing_now() + timedelta(seconds=1), record_id=98675)
    with pytest.raises(pcw_errors.PcwError) as caught:
        transition_item(db, _actor(owner), item.id, {"operation": "resolve",
            "expected_item_version": item.row_version, "reason": "Claimed delivery outcome",
            "customer_decision": "accepted",
            "evidence_refs": [{"type": "message", "id": inbound.id,
                               "revision": evidence_revision(inbound)}]}, "resolve-delivery-001")
    assert caught.value.error_code == "WORK_ITEM_TRANSITION_INVALID"


def test_last_required_action_can_complete_and_resolve_atomically(db):
    from app.customer.pcw_workitem_service import complete_action_v2
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    action.required_for_resolution = True
    conv = _conversation(db, account, external_id="required-action-case")
    message = _message(db, account, conv, external_id="required-answer", direction="out", sent_at=beijing_now(), record_id=98672)
    item.context_json = {"conversation_id": conv.id}
    db.flush()
    complete_action_v2(db, action_id=action.id, actor_user_id=owner.id, expected_action_version=1,
        expected_work_item_version=item.row_version, work_item_transition="resolve", outcome_code="replied", channel="email",
        occurred_at=beijing_now(), summary="Answered", evidence_message_ids=[message.id], idempotency_key="required-last-001")
    assert action.status == "done"
    assert item.state == "resolved"


def test_resolved_result_requires_required_source_to_remain_completed(db):
    from app.customer.work_item_source_service import attach_dependency, reconcile_item_inputs

    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, owner, item)
    action.status = "done"
    db.flush()
    attach_dependency(db, _actor(owner), item.id, {"source_domain": "action", "source_id": str(action.id),
        "title": "Required delivery", "required": True, "expected_item_version": item.row_version,
        "reason": "Must remain completed"}, "attach-complete-001")
    conv = _conversation(db, account, external_id="required-withdrawn")
    message = _message(db, account, conv, external_id="response", direction="out",
        sent_at=beijing_now(), record_id=98673)
    item.context_json = {"conversation_id": conv.id}
    transition_item(db, _actor(owner), item.id, {"operation": "resolve",
        "expected_item_version": item.row_version, "reason": "Answered with delivery accepted",
        "evidence_refs": [{"type": "message", "id": message.id,
                           "revision": evidence_revision(message)}]}, "resolve-required-001")
    assert item.result_validity == "verified"
    action.status = "pending"
    action.row_version += 1
    db.flush()
    reconcile_item_inputs(db, item)
    assert item.state == "resolved"
    assert item.result_validity == "review_required"
    assert item.source_valid is False


def test_read_summary_detects_real_source_withdrawal(db):
    from app.customer.work_item_query_service import list_items
    account, owner, item, message = resolved_inquiry(db)
    message.content_hash = "e" * 64
    db.flush()
    result = list_items(db, _actor(owner), view="need_me")
    assert result["summary"]["items_resolved"] == 0
    assert [row["item_id"] for row in result["items"]] == [item.id]


def test_read_only_source_observation_blocks_changed_input_without_writing(db):
    from app.customer import pcw_errors
    from app.customer.work_item_source_service import reconcile_item_inputs
    from sqlalchemy import event

    _account, owner, item, message = resolved_inquiry(db)
    db.commit()
    message.content_text = "The reply was corrected at source"
    message.content_hash = "d" * 64
    db.commit()
    version = item.source_revision
    events = db.query(WorkItemEvent).filter_by(item_id=item.id).count()
    writes = []
    def reject_flush(_session, _context, _instances):
        writes.append(True)
        raise AssertionError("read-only source observation attempted a write")
    event.listen(db, "before_flush", reject_flush)
    try:
        with pytest.raises(pcw_errors.PcwError) as caught:
            reconcile_item_inputs(db, item, read_only=True, actor_user_id=owner.id)
        assert caught.value.error_code == "SOURCE_INPUT_CHANGED"
        assert item.source_revision == version
        assert db.query(WorkItemEvent).filter_by(item_id=item.id).count() == events
        assert not writes
    finally:
        event.remove(db, "before_flush", reject_flush)


def test_pending_action_fact_content_change_invalidates_preparation(db):
    from app.customer.work_item_source_service import reconcile_item_inputs
    from tests.test_pcw_profile_revision import _candidate_fact
    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    fact = _candidate_fact(db, account, status="verified")
    action = _action(db, account, owner, item, evidence_fact_ids=[fact.id])
    assert action.feedback_json["source_revisions"]["fact"][str(fact.id)] == evidence_revision(fact)
    fact.value_json = {"value": "corrected customer requirement"}
    db.flush()
    reconcile_item_inputs(db, item)
    assert item.source_revision == 2
    assert item.source_valid is False
    assert action.evidence_status == "stale"
    recovered = transition_item(db, _actor(owner), item.id, {"operation": "reverify",
        "expected_item_version": item.row_version, "reason": "Checked the corrected color requirement",
        "evidence_refs": [{"type": "fact", "id": fact.id, "revision": evidence_revision(fact)}]},
        "reverify-source-001")
    assert recovered["item"]["state"] == "open"
    assert recovered["item"]["source_valid"] is True
    assert action.status == "cancelled"
    assert recovered["item"]["actions"][-1]["action_type"] == "review"


def test_reverify_replaces_stale_required_action_and_its_dependency(db):
    from app.customer.work_item_source_service import attach_dependency, reconcile_item_inputs
    from app.customer.work_item_service import require_dependencies
    from tests.test_pcw_profile_revision import _candidate_fact

    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    fact = _candidate_fact(db, account, status="verified")
    action = _action(db, account, owner, item, evidence_fact_ids=[fact.id])
    action.required_for_resolution = True
    db.flush()
    attach_dependency(db, _actor(owner), item.id, {"source_domain": "action", "source_id": str(action.id),
        "title": "Required customer delivery", "required": True, "expected_item_version": item.row_version,
        "reason": "Track the required reply"}, "attach-required-001")
    fact.value_json = {"value": "corrected requirement"}
    db.flush()
    reconcile_item_inputs(db, item)
    assert action.evidence_status == "stale"
    transition_item(db, _actor(owner), item.id, {"operation": "reverify",
        "expected_item_version": item.row_version, "reason": "Checked corrected requirement",
        "evidence_refs": [{"type": "fact", "id": fact.id, "revision": evidence_revision(fact)}]},
        "reverify-required-001")
    from app.customer.models import CustomerAction
    from app.customer.workbench_models import WorkItemDependency
    replacements = db.query(CustomerAction).filter(CustomerAction.parent_action_id == action.id).all()
    assert len(replacements) == 1
    replacement = replacements[0]
    assert action.status == "cancelled"
    assert replacement.required_for_resolution is True
    assert replacement.action_type == action.action_type
    assert replacement.channel == action.channel
    dependency = db.query(WorkItemDependency).filter_by(item_id=item.id, source_domain="action").one()
    assert dependency.source_id == str(replacement.id)
    with pytest.raises(Exception):
        require_dependencies(db, item, actor_user_id=owner.id)
    replacement.status = "done"
    db.flush()
    require_dependencies(db, item, actor_user_id=owner.id)


def test_reverify_replaces_action_required_only_by_dependency(db):
    from app.customer.work_item_source_service import attach_dependency, reconcile_item_inputs
    from tests.test_pcw_profile_revision import _candidate_fact
    from app.customer.models import CustomerAction
    from app.customer.workbench_models import WorkItemDependency

    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    fact = _candidate_fact(db, account, status="verified")
    action = _action(db, account, owner, item, evidence_fact_ids=[fact.id])
    assert action.required_for_resolution is False
    attach_dependency(db, _actor(owner), item.id, {"source_domain": "action", "source_id": str(action.id),
        "title": "Required reply", "required": True, "expected_item_version": item.row_version,
        "reason": "Customer needs the answer"}, "dependency-only-001")
    fact.value_json = {"value": "new requirement"}
    db.flush()
    reconcile_item_inputs(db, item)
    transition_item(db, _actor(owner), item.id, {"operation": "reverify",
        "expected_item_version": item.row_version, "reason": "Checked new requirement",
        "evidence_refs": [{"type": "fact", "id": fact.id, "revision": evidence_revision(fact)}]},
        "reverify-dependency-only-001")
    replacement = db.query(CustomerAction).filter(CustomerAction.parent_action_id == action.id).one()
    assert replacement.required_for_resolution is True
    assert db.query(WorkItemDependency).filter_by(item_id=item.id, source_domain="action").one().source_id == str(replacement.id)


def test_paused_item_can_reverify_required_source_without_resuming_action(db):
    from app.customer.work_item_source_service import reconcile_item_inputs
    from app.customer.models import CustomerAction
    from app.customer.pcw_workitem_service import complete_action_v2
    from tests.test_pcw_profile_revision import _candidate_fact
    from app.customer import pcw_errors

    account, owner = _customer_with_profile(db)
    item = _open_item(db, account)
    fact = _candidate_fact(db, account, status="verified")
    action = _action(db, account, owner, item, evidence_fact_ids=[fact.id])
    action.required_for_resolution = True
    item.state = "paused"
    item.paused_state = "open"
    item.resume_condition = "Manager review"
    fact.value_json = {"value": "corrected"}
    db.flush()
    reconcile_item_inputs(db, item)
    assert item.state == "paused" and not item.source_valid
    transition_item(db, _actor(owner), item.id, {"operation": "reverify",
        "expected_item_version": item.row_version, "reason": "Source now checked",
        "evidence_refs": [{"type": "fact", "id": fact.id, "revision": evidence_revision(fact)}]},
        "paused-reverify-001")
    replacement = db.query(CustomerAction).filter(CustomerAction.parent_action_id == action.id).one()
    assert item.state == "paused" and item.source_valid and replacement.status == "pending"
    with pytest.raises(pcw_errors.PcwError) as caught:
        complete_action_v2(db, action_id=replacement.id, actor_user_id=owner.id,
            expected_action_version=replacement.row_version, expected_work_item_version=item.row_version,
            outcome_code="contacted", channel="internal", occurred_at=beijing_now(), summary="Not yet",
            next_step="Review", next_step_due_at=beijing_now() + timedelta(days=1),
            idempotency_key="paused-action-block-001")
    assert caught.value.error_code == "WORK_ITEM_PAUSED"
    transition_item(db, _actor(owner), item.id, {"operation": "resume",
        "expected_item_version": item.row_version, "reason": "Manager approved continuation"},
        "resume-after-reverify-001")
    assert item.state == "open"
    assert db.query(CustomerAction).filter(CustomerAction.work_item_id == item.id,
        CustomerAction.status == "pending").count() == 1


def test_primary_transfer_fences_old_delegation_and_preserves_action_history(db):
    from app.customer.models import CustomerAssignment
    from app.customer.workbench_models import CustomerDelegation
    from app.customer.work_item_query_service import list_items
    from app.customer.work_item_service import item_access
    from app.customer import pcw_errors
    from tests.test_customer_workflow import _user, _grant_permission

    account, old_owner = _customer_with_profile(db)
    item = _open_item(db, account)
    action = _action(db, account, old_owner, item)
    db.add(CustomerDelegation(item_id=item.id, actor_user_id=old_owner.id,
        goal="Prepare response", scope_json={"mode": "prepare"}, status="active", input_revision=1))
    new_owner = _user(db, 9102)
    for permission in ("customer:read", "customer_pcw:read", "customer_pcw:write", "agent_runtime:invoke"):
        _grant_permission(db, new_owner.id, permission)
    old_assignment = db.query(CustomerAssignment).filter_by(customer_id=account.id, user_id=old_owner.id,
        assignment_role="primary", assignment_status="active").one()
    old_assignment.assignment_status = "ended"
    old_assignment.effective_to = beijing_now()
    db.add(CustomerAssignment(customer_id=account.id, user_id=new_owner.id,
        assignment_role="primary", assignment_status="active", assignment_source="manual",
        effective_from=beijing_now(), operated_by=new_owner.id,
        created_at=beijing_now(), updated_at=beijing_now()))
    db.commit()

    result = list_items(db, _actor(new_owner), view="need_me")
    assert [entry["item_id"] for entry in result["items"]] == [item.id]
    assert item.owner_user_id == new_owner.id
    assert action.owner_user_id == new_owner.id
    assert action.row_version == 2
    assert item.state == "blocked"
    assert item.source_revision == 2
    assert db.query(CustomerDelegation).one().status == "paused"
    assert db.query(WorkItemEvent).filter_by(item_id=item.id, event_type="assignment_changed").count() == 1
    with pytest.raises(pcw_errors.PcwError):
        item_access(db, _actor(old_owner), item.id)
