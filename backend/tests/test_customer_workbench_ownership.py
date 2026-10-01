"""Workbench references and authorization remain a closed ownership graph."""

import pytest

from app.customer import models
from app.customer.pcw_models import CustomerWorkItem, MaintenanceOccurrence, MaintenancePlan, ReorderWindow, SampleCase
from app.customer.workbench_models import (
    CustomerDelegation, WorkItemDependency, WorkItemEvent, WorkItemFeedback,
    WorkItemSourceDelivery,
)
from app.customer.ownership_execution_service import OwnershipExecutionError, execute_customer_ownership_change
from app.customer.ownership_service import require_effective_owner
from tests.test_customer_ownership_execution import NOW, _account, _fact, _payload, _seed, ownership_clock
from tests.test_customer_ownership_execution_review import _approve


def _item(db, source):
    row = CustomerWorkItem(id=720, customer_id=source.id, business_key="manual:ownership", business_cycle="first",
        work_type="manual", goal_type="manual", title="Accept customer result", state="open", context_json={},
        source_revision=1, source_valid=True, row_version=1, created_at=NOW, updated_at=NOW)
    db.add(row)
    db.flush()
    return row


def _action(db, source, actor, item):
    row = models.CustomerAction(id=721, customer_id=source.id, owner_user_id=actor.id,
        work_item_id=item.id, action_round=1, action_type="message", thread_group="manual", priority="medium",
        reason="Customer followup", next_action="Review response", action_date=NOW.date(), status="pending",
        feedback_json={}, source_event_ids=[], evidence_fact_ids=[], profile_version_id=source.current_profile_version_id,
        source_type="manual", policy_version="test", action_fingerprint="f" * 64, evidence_status="valid",
        generated_at=NOW, created_at=NOW, updated_at=NOW)
    db.add(row)
    db.flush()
    return row


def _execute(db, proposal, actor):
    return execute_customer_ownership_change(db, proposal_id=proposal.id, actor_user_id=actor.id, idempotency_key="b" * 64)


@pytest.mark.parametrize("action_type", ["merge", "split"])
def test_item_action_and_derived_children_move_without_rewriting_storage(db, action_type):
    source, target, evidence, _, actor, proposal = _seed(db, action_type)
    item = _item(db, source)
    action = _action(db, source, actor, item)
    event = WorkItemEvent(item_id=item.id, actor_user_id=actor.id, event_type="waiting", from_state="open",
        to_state="waiting", reason="Customer response awaited", evidence_refs=[{"type": "fact", "id": evidence.id}],
        input_revision=1, item_version=1, payload_json={}, occurred_at=NOW)
    dependency = WorkItemDependency(item_id=item.id, source_domain="action", source_id=str(action.id), title="Response")
    db.add_all([event, dependency])
    db.flush()
    _approve(proposal, _payload(db, source, target, evidence, action_type))
    _execute(db, proposal, actor)
    assert item.customer_id == action.customer_id == source.id
    assert require_effective_owner(db, "work_item", item.id) == target.id
    assert require_effective_owner(db, "action", action.id) == target.id
    assert event.item_id == dependency.item_id == item.id
    assert db.query(models.CustomerObjectOwnership).filter_by(object_type="work_item").count() == 1


@pytest.mark.parametrize("separate", ["item", "action", "evidence", "dependency"])
def test_split_rejects_separating_item_from_actions_and_evidence(db, separate):
    source, target, evidence, _, actor, proposal = _seed(db, "split")
    item = _item(db, source)
    action = _action(db, source, actor, item)
    if separate == "dependency":
        action.work_item_id = None
        db.add(WorkItemDependency(item_id=item.id, source_domain="action", source_id=str(action.id), title="Detached action"))
    item.resolution_evidence = [{"type": "fact", "id": evidence.id, "revision": "approved"}]
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    if separate != "dependency":
        kind = {"item": "work_item", "action": "action", "evidence": "fact"}[separate]
        for partition in payload["ownership_partitions"]:
            if partition["object_type"] == kind:
                partition["target_customer_id"] = source.id
    _approve(proposal, payload)
    db.commit()
    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)
    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"
    assert db.query(models.CustomerObjectOwnership).count() == 0
    assert db.get(CustomerWorkItem, item.id).customer_id == source.id
    assert db.get(models.CustomerChangeProposal, proposal.id).status == "approved"


@pytest.mark.parametrize("changed", ["item", "dependency", "event", "feedback", "delivery", "delegation", "evidence"])
def test_approved_basis_detects_in_place_workbench_changes(db, changed):
    source, target, evidence, _, actor, proposal = _seed(db)
    item = _item(db, source)
    action = _action(db, source, actor, item)
    item.resolution_evidence = [{"type": "fact", "id": evidence.id, "revision": "frozen"}]
    rows = {
        "dependency": WorkItemDependency(item_id=item.id, source_domain="action", source_id=str(action.id), title="Response"),
        "event": WorkItemEvent(item_id=item.id, event_type="result", from_state="open", to_state="open", reason="Result",
            evidence_refs=[], input_revision=1, item_version=1, payload_json={}, occurred_at=NOW),
        "feedback": WorkItemFeedback(item_id=item.id, actor_user_id=actor.id, target_id="fact:201", target_revision=1,
            dimension="accuracy", decision="yes", evidence_refs=[], updated_at=NOW),
        "delivery": WorkItemSourceDelivery(item_id=item.id, source_domain="action", source_event_id="source-event", source_revision=1, processed_at=NOW),
        "delegation": CustomerDelegation(item_id=item.id, actor_user_id=actor.id, goal="Prepare", scope_json={"customer_id": source.id}, input_revision=1),
    }
    db.add_all(rows.values())
    db.flush()
    _approve(proposal, _payload(db, source, target, evidence))
    if changed == "item":
        item.source_revision += 1
    elif changed == "dependency":
        rows[changed].source_id = "999999"
    elif changed == "event":
        rows[changed].evidence_refs = [{"type": "fact", "id": evidence.id}]
    elif changed == "feedback":
        rows[changed].decision = "no"
    elif changed == "delivery":
        rows[changed].source_revision += 1
    elif changed == "delegation":
        rows[changed].scope_json = {"customer_id": source.id, "new_scope": True}
    else:
        evidence.value_json = {"value": "Changed after approval"}
    db.commit()
    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)
    assert raised.value.error_code == "OWNERSHIP_EXECUTION_INVENTORY_STALE"
    assert db.query(models.CustomerObjectOwnership).count() == 0


@pytest.mark.parametrize("ref_location", ["item", "event", "feedback", "action"])
def test_cross_customer_evidence_cannot_follow_a_work_item(db, ref_location):
    source, target, evidence, _, actor, proposal = _seed(db)
    foreign = _account(db, 103, "FOREIGN")
    foreign_fact = _fact(db, foreign, 203)
    item = _item(db, source)
    ref = {"type": "fact", "id": foreign_fact.id, "revision": "foreign"}
    if ref_location == "item":
        item.resolution_evidence = [ref]
    elif ref_location == "event":
        db.add(WorkItemEvent(item_id=item.id, event_type="result", from_state="open", to_state="open", reason="Result",
            evidence_refs=[ref], input_revision=1, item_version=1, payload_json={}, occurred_at=NOW))
    elif ref_location == "feedback":
        db.add(WorkItemFeedback(item_id=item.id, actor_user_id=actor.id, target_id="fact:203", target_revision=1,
            dimension="accuracy", decision="no", evidence_refs=[ref], updated_at=NOW))
    else:
        _action(db, source, actor, item).evidence_fact_ids = [foreign_fact.id]
    db.flush()
    _approve(proposal, _payload(db, source, target, evidence))
    db.commit()
    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)
    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"
    assert db.query(models.CustomerObjectOwnership).count() == 0


def test_transfer_revokes_pending_delegation_generation(db):
    source, target, evidence, _, actor, proposal = _seed(db)
    item = _item(db, source)
    live = CustomerDelegation(item_id=item.id, actor_user_id=actor.id, goal="Prepare", scope_json={"customer_id": source.id}, input_revision=1)
    terminal = CustomerDelegation(item_id=item.id, actor_user_id=actor.id, goal="Historical", scope_json={}, input_revision=1, status="completed")
    db.add_all([live, terminal])
    db.flush()
    _approve(proposal, _payload(db, source, target, evidence))
    _execute(db, proposal, actor)
    assert live.status == "blocked" and live.generation == live.row_version == 2
    assert live.scope_json == {"customer_id": source.id}
    assert terminal.status == "completed" and terminal.generation == 1
    assert require_effective_owner(db, "work_item", item.id) == target.id


@pytest.mark.parametrize("run_status", ["queued", "running", "completed", "failed", "cancelled", "ambiguous"])
def test_transfer_requests_live_run_stop_without_rewriting_terminal_results(db, run_status):
    from app.agent_runtime.models import AgentProfile, AgentRun, AgentSession
    source, target, evidence, _, actor, proposal = _seed(db)
    item = _item(db, source)
    profile = AgentProfile(profile_key="ownership-test", version=1, name="Preparation", runtime="native",
        mode="interactive", model_preset="test", system_prompt="Prepare", prompt_hash="1" * 64)
    db.add(profile)
    db.flush()
    session = AgentSession(owner_user_id=actor.id, profile_id=profile.id, title="Preparation")
    db.add(session)
    db.flush()
    run = AgentRun(session_id=session.id, profile_id=profile.id, owner_user_id=actor.id,
        idempotency_key="ownership-run", trigger_type="user", source_runtime="native", mode="interactive",
        status=run_status, input_json={"customer_id": source.id}, context_snapshot={}, created_at=NOW, updated_at=NOW)
    db.add(run)
    db.flush()
    delegation = CustomerDelegation(item_id=item.id, actor_user_id=actor.id, goal="Prepare", scope_json={"customer_id": source.id},
        input_revision=1, last_run_id=run.id)
    db.add(delegation)
    db.flush()
    _approve(proposal, _payload(db, source, target, evidence))
    _execute(db, proposal, actor)
    assert delegation.generation == 2 and delegation.status == "blocked"
    assert run.status == run_status
    assert run.input_json == {"customer_id": source.id}
    assert run.cancel_requested == delegation.cancel_requested == (run_status in {"queued", "running"})


def _legacy_source(db, source, actor, item, kind):
    if kind == "sample":
        record = models.CustomerSourceRecord(id=731, customer_id=source.id, source_system="manual",
            source_account_key="global", authority_level="first_party", source_entity_type="order",
            external_record_id="sample-order", external_record_key_hash="c" * 64,
            data_classification="internal_business", visibility_scope="management", classification_reason="Test order",
            payload_schema_version="manual_v1", payload_json={}, content_hash="d" * 64, captured_at=NOW,
            processing_status="processed", created_at=NOW)
        db.add(record)
        db.flush()
        order = models.CustomerOrder(id=730, customer_id=source.id, source_system="manual", source_account_key="global",
            external_order_id="sample-order", source_record_id=record.id, order_status="confirmed", amount_usd=10, is_valid_business_order=True,
            source_hash="e" * 64, synced_at=NOW, created_at=NOW, updated_at=NOW)
        db.add(order)
        db.flush()
        row = SampleCase(customer_id=source.id, sample_order_id=order.id, item_set_hash="a" * 64,
            sample_item_ids_json=[], work_item_id=item.id, created_by=actor.id)
        origin = row
    elif kind == "reorder":
        row = ReorderWindow(customer_id=source.id, product_family="hair", anchor_batch_key="batch",
            occurrence_key="window", window_from=NOW.date(), window_to=NOW.date(), confidence="regular",
            work_item_id=item.id)
        origin = row
    else:
        origin = MaintenancePlan(customer_id=source.id, plan_type="manual", title="Followup", typed_payload={}, created_by=actor.id)
        db.add(origin)
        db.flush()
        row = MaintenanceOccurrence(plan_id=origin.id, occurrence_key="first", work_item_id=item.id, occurrence_date=NOW.date())
    db.add(row)
    db.flush()
    return row, origin


@pytest.mark.parametrize("kind", ["sample", "reorder", "maintenance"])
@pytest.mark.parametrize("action_type", ["merge", "split"])
def test_legacy_source_may_merge_but_cannot_be_separated_from_its_item(db, kind, action_type):
    source, target, evidence, _, actor, proposal = _seed(db, action_type)
    item = _item(db, source)
    row, origin = _legacy_source(db, source, actor, item, kind)
    _approve(proposal, _payload(db, source, target, evidence, action_type))
    db.commit()
    if action_type == "split":
        with pytest.raises(OwnershipExecutionError) as raised:
            _execute(db, proposal, actor)
        assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"
        assert db.query(models.CustomerObjectOwnership).count() == 0
    else:
        _execute(db, proposal, actor)
        assert require_effective_owner(db, "work_item", item.id) == target.id
    assert row.work_item_id == item.id
    assert origin.customer_id == source.id


@pytest.mark.parametrize("kind", ["sample", "reorder", "maintenance"])
def test_legacy_source_change_invalidates_approved_item_basis(db, kind):
    source, target, evidence, _, actor, proposal = _seed(db)
    item = _item(db, source)
    row, origin = _legacy_source(db, source, actor, item, kind)
    _approve(proposal, _payload(db, source, target, evidence))
    if kind == "sample":
        row.stage = "testing"
    elif kind == "reorder":
        row.confidence = "irregular"
    else:
        origin.typed_payload = {"changed_after_approval": True}
    db.commit()
    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)
    assert raised.value.error_code == "OWNERSHIP_EXECUTION_INVENTORY_STALE"


def test_birthday_contract_is_private_and_outside_profile_editing():
    from app.customer.contracts import FACT_REGISTRY, SOURCE_REGISTRY, DataClassification
    from app.customer.pcw_profile_service import FIELD_WHITELIST
    contract = FACT_REGISTRY["contact.birthday"]
    assert contract.value_types == {"object"}
    assert contract.data_classification == DataClassification.PERSONAL_CONTACT
    assert contract.allowed_purposes == {"maintenance"}
    assert contract.allowed_sources == {("manual", "contact"), ("okki", "contact")}
    assert "contact.birthday" not in FIELD_WHITELIST
    assert "contact.birthday" in SOURCE_REGISTRY[("manual", "contact")].allowed_fact_keys
    assert SOURCE_REGISTRY[("okki", "contact")].promotion_ceiling == "identified"
