from datetime import timedelta

import pytest

from app.auth.models import ArkUser
from app.customer import models
from app.customer.ownership_execution_service import (
    OwnershipExecutionError,
    execute_customer_ownership_change,
)
from app.customer.proposal_service import canonical_action_hash
from tests.test_customer_ownership_execution import NOW, _payload, _seed


def _approve(proposal, payload):
    action_hash = canonical_action_hash(
        action_type=proposal.action_type,
        customer_id=proposal.customer_id,
        target_customer_id=proposal.target_customer_id,
        payload_json=payload,
        profile_version_id=proposal.profile_version_id,
        evidence_fact_ids=proposal.evidence_fact_ids,
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash


def _execute(db, proposal, actor, key="r"):
    return execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key=key * 64,
    )


def _assignment(db, row_id, customer_id, user_id, role="primary"):
    row = models.CustomerAssignment(
        id=row_id, customer_id=customer_id, user_id=user_id,
        assignment_role=role, assignment_status="active",
        assignment_source="manual", effective_from=NOW,
        change_reason="seed", operated_by=user_id,
        created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _dnc(db, row_id, customer_id, actor_id):
    row = models.CustomerAnnotation(
        id=row_id, customer_id=customer_id, annotation_type="do_not_contact",
        content_schema_version="v1", content_json={"reason": "request"},
        policy_scope_type="global", policy_effective_at=NOW,
        visibility="management", data_classification="restricted_internal",
        status="active", authored_by=actor_id, created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def test_execution_requires_active_human_actor(db):
    _source, _target, _evidence, _name, actor, proposal = _seed(db)
    actor.is_active = False
    db.flush()

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_ACTOR_INVALID"


def test_dnc_existing_record_cannot_be_the_source_record(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    _dnc(db, 401, source.id, actor.id)
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["dnc"] = {
        "source_ids": [401],
        "rebuilds": [{
            "source_id": 401, "existing_id": 401,
            "target_customer_id": target.id,
        }],
    }
    _approve(proposal, payload)
    proposal_id, actor_id = proposal.id, actor.id
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal_id, actor_user_id=actor_id,
            idempotency_key="r" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_TRANSITION_PLAN_INVALID"
    assert db.get(models.CustomerAnnotation, 401).status == "active"


def test_split_without_retaining_source_cannot_leave_a_root_on_source(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    payload = _payload(db, source, target, evidence, "split", retain_source=False)
    payload["ownership_partitions"][0]["target_customer_id"] = source.id
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_DESTINATION_INVALID"


def test_connected_roots_cannot_be_split_across_logical_targets(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    source_record = models.CustomerSourceRecord(
        id=501, customer_id=source.id, source_system="manual",
        source_account_key="global", authority_level="manual",
        source_entity_type="company", external_record_id="source-501",
        external_record_key_hash=f"{501:064x}",
        data_classification="internal_business", visibility_scope="management",
        classification_reason="test", payload_schema_version="manual_v1",
        payload_json={}, content_hash=f"{502:064x}", captured_at=NOW,
        processing_status="processed", created_at=NOW,
    )
    db.add(source_record)
    db.flush()
    db.add(models.CustomerFactEvidenceLink(
        id=502, customer_id=source.id, fact_id=evidence.id,
        relation_type="supports", evidence_kind="source_record",
        source_record_id=source_record.id,
        evidence_content_hash=source_record.content_hash,
        locator_json={"json_path": "$"},
        data_classification="internal_business",
        evidence_fingerprint=f"{503:064x}", created_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    for item in payload["ownership_partitions"]:
        if item["object_type"] == "fact":
            item["target_customer_id"] = source.id
        if item["object_type"] == "source_record":
            item["target_customer_id"] = target.id
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT"


def test_assignment_projection_can_resolve_merge_primary_conflict(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    other = ArkUser(
        id=902, username="keeper-owner", password_hash="x",
        real_name="Keeper Owner", is_active=True, must_change_password=False,
        created_at=NOW, updated_at=NOW,
    )
    db.add(other)
    db.flush()
    _assignment(db, 301, source.id, actor.id)
    _assignment(db, 302, target.id, other.id)
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["assignments"] = {
        "source_ids": [301],
        "rebuilds": [{
            "source_id": 301, "new_id": 303,
            "target_customer_id": target.id,
            "user_id": actor.id, "assignment_role": "collaborator",
        }],
    }
    _approve(proposal, payload)

    _execute(db, proposal, actor)

    rebuilt = db.get(models.CustomerAssignment, 303)
    assert (rebuilt.user_id, rebuilt.assignment_role) == (actor.id, "collaborator")


def test_idempotent_replay_returns_first_frozen_open_proposal_plan(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    other = models.CustomerChangeProposal(
        id=802, customer_id=source.id, target_customer_id=target.id,
        action_type="merge", payload_schema_version="customer_merge_v1",
        payload_json={}, evidence_fact_ids=[evidence.id],
        profile_version_id=source.current_profile_version_id,
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="1" * 64,
        status="draft", expires_at=NOW + timedelta(days=30),
        created_at=NOW, updated_at=NOW,
    )
    db.add(other)
    db.flush()
    first = _execute(db, proposal, actor)
    assert first.open_proposal_plan["supersede"] == [
        {"proposal_id": 802, "next_status": "superseded"}
    ]
    other.status = "superseded"
    db.flush()

    repeated = _execute(db, proposal, actor)

    assert repeated == first


def test_execution_invalidates_list_and_current_target_projections(db):
    source, target, _evidence, _name, actor, proposal = _seed(db)
    for customer in (source, target):
        db.add(models.CustomerListProjection(
            customer_id=customer.id, has_valid_order=False, valid_order_count=0,
            valid_order_amount_usd=0, engagement_health="unknown",
            open_opportunity_count=0, global_claim_blocked=False,
            has_active_dnc=False, data_quality_score=0,
            profile_version_id=customer.current_profile_version_id,
            compiled_at=NOW,
        ))
        db.add(models.CustomerTargetMatch(
            id=700 + customer.id, customer_id=customer.id,
            target_profile_id=999, policy_version="v1", match_score=50,
            score_reasons={}, match_status="qualified", evidence_fact_ids=[],
            is_current=True, match_fingerprint=f"{700 + customer.id:064x}",
            computed_at=NOW,
        ))
    db.flush()

    _execute(db, proposal, actor)

    assert db.query(models.CustomerListProjection).count() == 0
    assert db.query(models.CustomerTargetMatch).filter_by(is_current=True).count() == 0


def test_customer_relation_preserves_unaffected_third_party_endpoint(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    third = models.CustomerAccount(
        id=103, customer_code="THIRD", display_name="THIRD",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="discovered", relationship_stage_changed_at=NOW,
        relationship_stage_reason="seed",
        record_status="active", identity_confidence=1, profile_completeness=10,
        profile_input_seq=0, created_at=NOW, updated_at=NOW,
    )
    db.add(third)
    db.flush()
    db.add(models.CustomerRelationship(
        id=601, from_customer_id=source.id, to_customer_id=third.id,
        relationship_type="subsidiary_of", verification_status="verified",
        confidence=1, confidence_method_version="test_v1",
        confidence_components_json={}, relationship_fingerprint="6" * 64,
        effective_from=NOW, created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["customer_relationships"] = {
        "source_ids": [601],
        "rebuilds": [{
            "source_id": 601, "new_id": 602,
            "from_customer_id": target.id, "to_customer_id": third.id,
        }],
    }
    _approve(proposal, payload)

    _execute(db, proposal, actor)

    rebuilt = db.get(models.CustomerRelationship, 602)
    assert (rebuilt.from_customer_id, rebuilt.to_customer_id) == (target.id, third.id)


def test_customer_relation_rejects_rewriting_third_party_endpoint(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    for row_id in (103, 104):
        db.add(models.CustomerAccount(
            id=row_id, customer_code=f"THIRD-{row_id}", display_name=f"THIRD-{row_id}",
            entity_type="registered_company", identity_status="verified",
            relationship_stage="discovered", relationship_stage_changed_at=NOW,
            relationship_stage_reason="seed",
            record_status="active", identity_confidence=1, profile_completeness=10,
            profile_input_seq=0, created_at=NOW, updated_at=NOW,
        ))
    db.flush()
    db.add(models.CustomerRelationship(
        id=601, from_customer_id=source.id, to_customer_id=103,
        relationship_type="subsidiary_of", verification_status="verified",
        confidence=1, confidence_method_version="test_v1",
        confidence_components_json={}, relationship_fingerprint="7" * 64,
        effective_from=NOW, created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["customer_relationships"] = {
        "source_ids": [601],
        "rebuilds": [{
            "source_id": 601, "new_id": 602,
            "from_customer_id": target.id, "to_customer_id": 104,
        }],
    }
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_TRANSITION_PLAN_INVALID"


def test_nonretained_split_transition_cannot_rebuild_to_source(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    _assignment(db, 301, source.id, actor.id)
    payload = _payload(db, source, target, evidence, "split", retain_source=False)
    payload["transition_plan"]["assignments"] = {
        "source_ids": [301],
        "rebuilds": [{
            "source_id": 301, "new_id": 302,
            "target_customer_id": source.id,
        }],
    }
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_DESTINATION_INVALID"


def test_merge_dnc_union_keeps_one_active_policy_on_keeper(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    _dnc(db, 401, source.id, actor.id)
    _dnc(db, 402, target.id, actor.id)
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["dnc"] = {
        "source_ids": [401],
        "rebuilds": [{
            "source_id": 401, "existing_id": 402,
            "target_customer_id": target.id,
        }],
    }
    _approve(proposal, payload)

    _execute(db, proposal, actor)

    assert db.get(models.CustomerAnnotation, 401).status == "revoked"
    assert db.get(models.CustomerAnnotation, 402).status == "active"


def test_split_identity_conflicts_are_checked_per_projected_customer(db):
    source, target, evidence, _name, actor, proposal = _seed(db, "split")
    for row_id, value in ((601, "registration-a"), (602, "registration-b")):
        db.add(models.CustomerExternalIdentity(
            id=row_id, customer_id=source.id, source_system="registry",
            source_account_key="global", identifier_type="business_id",
            raw_value=value, normalized_value=value, identity_strength="strong",
            cardinality="one_to_one", auto_match_ceiling="verified",
            verification_status="verified", confidence=1,
            confidence_method_version="test_v1", confidence_components_json={},
            is_primary=True, status="active", identity_fingerprint=f"{row_id:064x}",
            first_seen_at=NOW, last_seen_at=NOW, created_at=NOW, updated_at=NOW,
        ))
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    identities = [item for item in payload["ownership_partitions"]
                  if item["object_type"] == "external_identity"]
    identities[0]["target_customer_id"] = source.id
    identities[1]["target_customer_id"] = target.id
    _approve(proposal, payload)

    _execute(db, proposal, actor)

    assert {
        db.get(models.CustomerObjectOwnership, ("external_identity", row_id)).current_customer_id
        for row_id in (601, 602)
    } == {source.id, target.id}


def test_projected_identity_includes_third_storage_overlay_owned_by_source(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    third = models.CustomerAccount(
        id=103, customer_code="STORAGE", display_name="STORAGE",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="discovered", relationship_stage_changed_at=NOW,
        relationship_stage_reason="seed", record_status="active",
        identity_confidence=1, profile_completeness=10, profile_input_seq=0,
        created_at=NOW, updated_at=NOW,
    )
    db.add(third)
    for row_id, customer_id, value in (
        (611, third.id, "registration-overlay"),
        (612, target.id, "registration-target"),
    ):
        db.add(models.CustomerExternalIdentity(
            id=row_id, customer_id=customer_id, source_system="registry",
            source_account_key="global", identifier_type="business_id",
            raw_value=value, normalized_value=value, identity_strength="strong",
            cardinality="one_to_one", auto_match_ceiling="verified",
            verification_status="verified", confidence=1,
            confidence_method_version="test_v1", confidence_components_json={},
            is_primary=True, status="active", identity_fingerprint=f"{row_id:064x}",
            first_seen_at=NOW, last_seen_at=NOW, created_at=NOW, updated_at=NOW,
        ))
    db.flush()
    db.add(models.CustomerObjectOwnership(
        object_type="external_identity", object_id=611,
        storage_customer_id=third.id, current_customer_id=source.id,
        ownership_version=1, last_change_proposal_id=proposal.id,
        last_action_type="split", created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor)

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_IDENTITY_CONFLICT"


def test_replay_uses_frozen_execution_actor_even_if_later_inactive(db):
    _source, _target, _evidence, _name, actor, proposal = _seed(db)
    first = _execute(db, proposal, actor, key="y")
    other = ArkUser(
        id=902, username="other-admin", password_hash="x", real_name="Other Admin",
        is_active=True, must_change_password=False, created_at=NOW, updated_at=NOW,
    )
    db.add(other)
    actor.is_active = False
    db.flush()

    assert _execute(db, proposal, actor, key="y") == first
    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, other, key="y")
    assert raised.value.error_code == "OWNERSHIP_EXECUTION_ACTOR_MISMATCH"


def test_redirect_requires_exact_declared_target_profile(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    db.add(models.CustomerChangeProposal(
        id=802, customer_id=source.id, target_customer_id=target.id,
        action_type="merge", payload_schema_version="customer_merge_v1",
        payload_json={}, evidence_fact_ids=[evidence.id],
        profile_version_id=source.current_profile_version_id,
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="1" * 64,
        status="draft", expires_at=NOW + timedelta(days=30),
        created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    payload["proposal_redirects"] = [{
        "proposal_id": 802,
        "target_customer_id": target.id,
        "target_profile_version_id": source.current_profile_version_id,
    }]
    _approve(proposal, payload)

    with pytest.raises(OwnershipExecutionError) as raised:
        _execute(db, proposal, actor, key="7")

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_REDIRECT_PLAN_INVALID"


def test_redirect_result_freezes_target_profile_version(db):
    source, target, evidence, _name, actor, proposal = _seed(db)
    db.add(models.CustomerChangeProposal(
        id=802, customer_id=source.id, target_customer_id=target.id,
        action_type="merge", payload_schema_version="customer_merge_v1",
        payload_json={}, evidence_fact_ids=[evidence.id],
        profile_version_id=source.current_profile_version_id,
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="2" * 64,
        status="draft", expires_at=NOW + timedelta(days=30),
        created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    payload["proposal_redirects"] = [{
        "proposal_id": 802, "target_customer_id": target.id,
        "target_profile_version_id": target.current_profile_version_id,
    }]
    _approve(proposal, payload)

    result = _execute(db, proposal, actor, key="8")

    assert result.open_proposal_plan["redirect"][0]["target_profile_version_id"] == 1102
