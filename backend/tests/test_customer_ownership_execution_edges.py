from datetime import timedelta

import pytest

from app.customer import models
from app.customer.ownership_execution_contract import ExecutionContractError
from app.customer.ownership_execution_service import (
    OwnershipExecutionError,
    execute_customer_ownership_change,
)
from tests.test_customer_ownership_execution import NOW, _fact, _payload, _seed
from tests.test_customer_ownership_execution_review import _approve


def _execute(db, proposal, actor, key):
    return execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key=key * 64,
    )


def _research(db, customer_id, row_id, evidence_fact_ids):
    row = models.CustomerResearchTask(
        id=row_id, customer_id=customer_id, task_type="company_research",
        task_status="pending", gate_status="pending", result_review_status="pending",
        selection_reason="merge test", research_policy_version="v1",
        task_fingerprint=f"{row_id:064x}", input_snapshot={},
        data_classification="internal_business", visibility_scope="management",
        classification_reason="test", evidence_fact_ids=evidence_fact_ids,
        lease_generation=0, attempt_count=0, created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def test_fact_subject_conversation_must_share_final_owner(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    conversation = models.CustomerConversation(
        id=701, customer_id=source.id, source_system="manual",
        source_account_key="global", external_conversation_id="conversation-701",
        channel="email", conversation_status="active", created_at=NOW, updated_at=NOW,
    )
    db.add(conversation)
    evidence.subject_type = "conversation"
    evidence.subject_id = conversation.id
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    for item in payload["ownership_partitions"]:
        if item["object_type"] == "fact":
            item["target_customer_id"] = source.id
        elif item["object_type"] == "conversation":
            item["target_customer_id"] = target.id
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "s")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_fact_evidence_json_fact_index_must_share_final_owner(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    supporting = _fact(db, source, 702)
    evidence.evidence_json = {"fact_ids": [supporting.id]}
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    for item in payload["ownership_partitions"]:
        if item["object_type"] == "fact" and item["object_id"] == evidence.id:
            item["target_customer_id"] = source.id
        elif item["object_type"] == "fact" and item["object_id"] == supporting.id:
            item["target_customer_id"] = target.id
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "t")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_unfinished_research_clone_evidence_must_share_target_owner(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    task = _research(db, source.id, 703, [evidence.id])
    payload = _payload(db, source, target, evidence, "split")
    next(item for item in payload["ownership_partitions"]
         if item["object_type"] == "fact")["target_customer_id"] = source.id
    payload["transition_plan"]["research_tasks"] = {
        "source_ids": [task.id],
        "rebuilds": [{
            "source_id": task.id, "new_id": 704,
            "target_customer_id": target.id,
        }],
    }
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "u")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_acquisition_may_keep_historical_link_to_ended_research_task(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    task = _research(db, source.id, 703, [])
    attribution = models.CustomerAcquisitionAttribution(
        id=705, customer_id=source.id, origin_type="research",
        origin_ref_type="research_task", origin_ref_id=task.id,
        research_task_id=task.id, attribution_role="first_touch",
        attribution_weight=1, policy_version="v1", allocated_cost_usd=0,
        attribution_fingerprint=f"{705:064x}", occurred_at=NOW, created_at=NOW,
    )
    db.add(attribution)
    db.flush()
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["research_tasks"] = {
        "source_ids": [task.id],
        "rebuilds": [{
            "source_id": task.id, "new_id": 704,
            "target_customer_id": target.id,
        }],
    }
    _approve(proposal, payload)

    _execute(db, proposal, actor, "v")

    assert db.get(models.CustomerResearchTask, task.id).task_status == "cancelled"
    assert db.get(models.CustomerResearchTask, 704).customer_id == target.id
    owner = db.get(models.CustomerObjectOwnership, ("acquisition_attribution", attribution.id))
    assert owner.current_customer_id == target.id


def test_contact_relationship_source_fact_must_share_rebuild_target(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    contact = models.CustomerContact(
        id=706, display_name="Buyer", identity_status="verified", confidence=1,
        confidence_method_version="v1", confidence_components_json={},
        record_status="active", created_at=NOW, updated_at=NOW,
    )
    db.add(contact)
    db.flush()
    relationship = models.CustomerContactRelationship(
        id=707, customer_id=source.id, contact_id=contact.id,
        relationship_type="employee", verification_status="verified", confidence=1,
        confidence_method_version="v1", confidence_components_json={},
        source_fact_id=evidence.id, relationship_fingerprint=f"{707:064x}",
        effective_from=NOW, created_at=NOW, updated_at=NOW,
    )
    db.add(relationship)
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    next(item for item in payload["ownership_partitions"]
         if item["object_type"] == "fact")["target_customer_id"] = source.id
    payload["transition_plan"]["contact_relationships"] = {
        "source_ids": [relationship.id],
        "rebuilds": [{
            "source_id": relationship.id, "new_id": 708,
            "target_customer_id": target.id,
        }],
    }
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "w")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_opportunity_event_evidence_must_share_opportunity_owner(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    opportunity = models.CustomerOpportunity(
        id=709, customer_id=source.id, opportunity_type="inquiry", source="manual",
        source_system="manual", source_account_key="global", source_key="opp-709",
        priority_level="A", confidence_score=80, urgency="high", title="Inquiry",
        product_requirement_json={}, competitor_json={}, evidence_fact_ids=[],
        status="open", stage_entered_at=NOW, created_at=NOW, updated_at=NOW,
    )
    db.add(opportunity)
    db.flush()
    db.add(models.CustomerOpportunityEvent(
        id=710, opportunity_id=opportunity.id, customer_id=source.id,
        event_type="created", event_payload={}, evidence_fact_ids=[evidence.id],
        occurred_at=NOW, event_fingerprint=f"{710:064x}", created_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    for item in payload["ownership_partitions"]:
        if item["object_type"] == "fact":
            item["target_customer_id"] = source.id
        elif item["object_type"] == "opportunity":
            item["target_customer_id"] = target.id
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "x")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_terminal_research_linked_acquisition_must_share_final_owner(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    task = _research(db, source.id, 711, [])
    task.task_status = "completed"
    task.gate_status = "passed"
    task.result_review_status = "approved"
    task.finished_at = NOW
    attribution = models.CustomerAcquisitionAttribution(
        id=712, customer_id=source.id, origin_type="research",
        origin_ref_type="research_task", origin_ref_id=task.id,
        research_task_id=task.id, attribution_role="first_touch",
        attribution_weight=1, policy_version="v1", allocated_cost_usd=0,
        attribution_fingerprint=f"{712:064x}", occurred_at=NOW, created_at=NOW,
    )
    db.add(attribution)
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    for item in payload["ownership_partitions"]:
        if item["object_type"] == "research_task":
            item["target_customer_id"] = source.id
        elif item["object_type"] == "acquisition_attribution":
            item["target_customer_id"] = target.id
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "1")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_contact_relationship_source_fact_may_move_with_target(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    contact = models.CustomerContact(
        id=713, display_name="Buyer", identity_status="verified", confidence=1,
        confidence_method_version="v1", confidence_components_json={},
        record_status="active", created_at=NOW, updated_at=NOW,
    )
    db.add(contact)
    db.flush()
    relation = models.CustomerContactRelationship(
        id=714, customer_id=source.id, contact_id=contact.id,
        relationship_type="employee", verification_status="verified", confidence=1,
        confidence_method_version="v1", confidence_components_json={},
        source_fact_id=evidence.id, relationship_fingerprint=f"{714:064x}",
        effective_from=NOW, created_at=NOW, updated_at=NOW,
    )
    db.add(relation)
    db.flush()
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["contact_relationships"] = {
        "source_ids": [relation.id],
        "rebuilds": [{
            "source_id": relation.id, "new_id": 715,
            "target_customer_id": target.id,
        }],
    }
    _approve(proposal, payload)

    _execute(db, proposal, actor, "2")

    assert db.get(models.CustomerContactRelationship, 715).customer_id == target.id


def _customer_relation(db, source_id, third_id, fact_id, row_id):
    row = models.CustomerRelationship(
        id=row_id, from_customer_id=source_id, to_customer_id=third_id,
        relationship_type="subsidiary_of", verification_status="verified", confidence=1,
        confidence_method_version="v1", confidence_components_json={},
        source_fact_id=fact_id, relationship_fingerprint=f"{row_id:064x}",
        effective_from=NOW, created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def test_customer_relationship_source_fact_must_follow_replaced_endpoint(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    third = models.CustomerAccount(
        id=103, customer_code="THIRD", display_name="THIRD",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="discovered", relationship_stage_changed_at=NOW,
        relationship_stage_reason="seed", record_status="active",
        identity_confidence=1, profile_completeness=0, profile_input_seq=0,
        created_at=NOW, updated_at=NOW,
    )
    db.add(third)
    db.flush()
    relation = _customer_relation(db, source.id, third.id, evidence.id, 716)
    payload = _payload(db, source, target, evidence, "split")
    next(item for item in payload["ownership_partitions"]
         if item["object_type"] == "fact")["target_customer_id"] = source.id
    payload["transition_plan"]["customer_relationships"] = {
        "source_ids": [relation.id],
        "rebuilds": [{
            "source_id": relation.id, "new_id": 717,
            "from_customer_id": target.id, "to_customer_id": third.id,
        }],
    }
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "3")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_opportunity_message_source_ref_alias_must_share_conversation_owner(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    source_record = models.CustomerSourceRecord(
        id=718, customer_id=source.id, source_system="manual",
        source_account_key="global", authority_level="manual",
        source_entity_type="conversation", external_record_id="record-718",
        external_record_key_hash=f"{718:064x}", data_classification="internal_business",
        visibility_scope="management", classification_reason="test",
        payload_schema_version="manual_v1", payload_json={}, content_hash=f"{719:064x}",
        captured_at=NOW, processing_status="processed", created_at=NOW,
    )
    conversation = models.CustomerConversation(
        id=719, customer_id=source.id, source_system="manual",
        source_account_key="global", external_conversation_id="conversation-719",
        channel="email", conversation_status="active", created_at=NOW, updated_at=NOW,
    )
    db.add_all([source_record, conversation])
    db.flush()
    message = models.CustomerMessage(
        id=720, conversation_id=conversation.id, external_message_id="message-720",
        direction="inbound", sender_type="customer", content_type="text",
        attachment_meta_json=[], source_record_id=source_record.id,
        content_hash=f"{720:064x}", sent_at=NOW, captured_at=NOW, created_at=NOW,
    )
    opportunity = models.CustomerOpportunity(
        id=721, customer_id=source.id, opportunity_type="inquiry", source="manual",
        source_system="manual", source_account_key="global", source_key="opp-721",
        source_ref_type="message", source_ref_id=str(message.id), priority_level="A",
        confidence_score=80, urgency="high", title="Inquiry", product_requirement_json={},
        competitor_json={}, evidence_fact_ids=[], status="open", stage_entered_at=NOW,
        created_at=NOW, updated_at=NOW,
    )
    db.add_all([message, opportunity])
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    for item in payload["ownership_partitions"]:
        if item["object_type"] in {"source_record", "conversation"}:
            item["target_customer_id"] = source.id
        elif item["object_type"] == "opportunity":
            item["target_customer_id"] = target.id
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "4")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_customer_relationship_source_fact_may_move_with_replaced_endpoint(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    third = models.CustomerAccount(
        id=103, customer_code="THIRD", display_name="THIRD",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="discovered", relationship_stage_changed_at=NOW,
        relationship_stage_reason="seed", record_status="active",
        identity_confidence=1, profile_completeness=0, profile_input_seq=0,
        created_at=NOW, updated_at=NOW,
    )
    db.add(third)
    db.flush()
    relation = _customer_relation(db, source.id, third.id, evidence.id, 722)
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["customer_relationships"] = {
        "source_ids": [relation.id],
        "rebuilds": [{
            "source_id": relation.id, "new_id": 723,
            "from_customer_id": target.id, "to_customer_id": third.id,
        }],
    }
    _approve(proposal, payload)

    _execute(db, proposal, actor, "5")

    rebuilt = db.get(models.CustomerRelationship, 723)
    assert (rebuilt.from_customer_id, rebuilt.to_customer_id) == (target.id, third.id)


def test_postcondition_edge_drift_rolls_back_every_write(db, monkeypatch):
    source, _target, _evidence, _name, actor, proposal = _seed(db)
    source_id, proposal_id, actor_id = source.id, proposal.id, actor.id
    db.commit()

    def fail_after_write(*_args, **_kwargs):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT")

    monkeypatch.setattr(
        "app.customer.ownership_execution_apply.validate_graph_targets",
        fail_after_write,
    )
    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal_id, actor_user_id=actor_id,
            idempotency_key="6" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"
    assert db.get(models.CustomerAccount, source_id).record_status == "active"
    assert db.get(models.CustomerChangeProposal, proposal_id).status == "approved"
    assert db.query(models.CustomerObjectOwnership).count() == 0


def _split_source_redirect(db, *, wrong_profile):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    db.add(models.CustomerChangeProposal(
        id=802, customer_id=source.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, evidence_fact_ids=[evidence.id],
        profile_version_id=source.current_profile_version_id,
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="3" * 64,
        status="draft", expires_at=NOW + timedelta(days=30),
        created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence, "split", retain_source=True)
    payload["proposal_redirects"] = [{
        "proposal_id": 802, "target_customer_id": source.id,
        "target_profile_version_id": (
            target.current_profile_version_id if wrong_profile
            else source.current_profile_version_id
        ),
    }]
    _approve(proposal, payload)
    return source, actor, proposal


def test_retained_split_may_redirect_to_frozen_source_profile(db):
    source, actor, proposal = _split_source_redirect(db, wrong_profile=False)

    result = _execute(db, proposal, actor, "9")

    redirect = result.open_proposal_plan["redirect"][0]
    assert (redirect["target_customer_id"], redirect["target_profile_version_id"]) == (
        source.id, 1101,
    )


def test_retained_split_rejects_wrong_source_profile_redirect(db):
    _source, actor, proposal = _split_source_redirect(db, wrong_profile=True)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, "0")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_REDIRECT_PLAN_INVALID"
