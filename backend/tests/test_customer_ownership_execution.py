"""Atomic merge/split execution over logical customer ownership."""

from datetime import datetime, timedelta

import pytest

from app.auth.models import ArkUser
from app.customer import models
from app.customer.ownership_execution_service import (
    OwnershipExecutionError,
    build_execution_basis,
    execute_customer_ownership_change,
)
from app.customer.proposal_service import canonical_action_hash


NOW = datetime(2026, 8, 31, 9, 0)


def _account(db, row_id, code):
    row = models.CustomerAccount(
        id=row_id, customer_code=code, display_name=code,
        canonical_company_name=f"{code} LLC", entity_type="registered_company",
        identity_status="verified", relationship_stage="discovered",
        relationship_stage_changed_at=NOW, relationship_stage_reason="seed",
        record_status="active", identity_confidence=1, profile_completeness=80,
        profile_input_seq=3, created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    profile = models.CustomerProfileVersion(
        id=row_id + 1000, customer_id=row.id, version_no=1,
        profile_schema_version="customer_profile_v1", canonicalization_version="jcs_v1",
        input_seq=row.profile_input_seq, profile_json={}, section_hashes={},
        section_data_as_of={}, evidence_fact_ids=[], change_summary={"changes": []},
        compiler_version="test_v1", profile_fingerprint=f"{row_id + 1000:064x}",
        compiled_at=NOW, created_at=NOW,
    )
    db.add(profile)
    db.flush()
    row.current_profile_version_id = profile.id
    db.flush()
    return row


def _fact(db, customer, row_id):
    row = models.CustomerFact(
        id=row_id, customer_id=customer.id, subject_type="customer",
        subject_id=None, fact_key="identity.company_name",
        fact_layer="confirmed", value_type="string", value_json={"value": customer.display_name},
        verification_status="verified",
        confidence=1, confidence_method_version="test_v1", confidence_components_json={},
        data_classification="internal_business", visibility_scope="management",
        classification_reason="merge evidence", evidence_json={},
        fact_fingerprint=f"{row_id:064x}", observed_at=NOW, created_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _name(db, customer, row_id):
    row = models.CustomerName(
        id=row_id, customer_id=customer.id, name=customer.display_name,
        normalized_name=customer.display_name.lower(), name_type="legal",
        verification_status="verified", confidence=1,
        confidence_method_version="test_v1", confidence_components_json={},
        name_fingerprint=f"{row_id:064x}", first_seen_at=NOW, last_seen_at=NOW,
        created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _actor(db):
    row = ArkUser(
        id=901, username="merge-admin", password_hash="x", real_name="Merge Admin",
        is_active=True, must_change_password=False, created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _payload(db, source, target, evidence, action_type="merge", **changes):
    basis = build_execution_basis(
        db, source_customer_id=source.id, target_customer_ids=[target.id],
    )
    payload = {
        "ownership_registry_version": basis["ownership_registry_version"],
        "source_customer_id": source.id,
        "target_customer_ids": [target.id],
        "source_profile_version_id": source.current_profile_version_id,
        "source_profile_input_seq": source.profile_input_seq,
        "target_profile_versions": [{
            "customer_id": target.id,
            "profile_version_id": target.current_profile_version_id,
            "profile_input_seq": target.profile_input_seq,
        }],
        "evidence_fact_ids": [evidence.id],
        "root_inventory": basis["root_inventory"],
        "ownership_partitions": basis["ownership_partitions"],
        "transition_plan": {
            key: {"source_ids": [], "rebuilds": []}
            for key in (
                "assignments", "contact_relationships", "customer_relationships",
                "dnc", "qualifications", "research_tasks",
            )
        },
        "proposal_redirects": [],
        "reason_code": "verified_duplicate",
        "reason_text": "Confirmed duplicate customer accounts",
    }
    payload["keep_customer_id" if action_type == "merge" else "retain_source"] = (
        target.id if action_type == "merge" else True
    )
    payload.update(changes)
    return payload


def _proposal(db, source, target, evidence, payload, row_id=801, action_type="merge"):
    action_hash = canonical_action_hash(
        action_type=action_type, customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    row = models.CustomerChangeProposal(
        id=row_id, customer_id=source.id, target_customer_id=target.id,
        action_type=action_type, payload_schema_version=f"customer_{action_type}_v1",
        payload_json=payload, evidence_fact_ids=[evidence.id],
        profile_version_id=source.current_profile_version_id, risk_level="critical",
        data_classification="restricted_internal", visibility_scope="management",
        action_hash=action_hash, approved_action_hash=action_hash, status="approved",
        expires_at=NOW + timedelta(days=30), decided_at=NOW,
        created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _seed(db, action_type="merge"):
    source = _account(db, 101, "SOURCE")
    target = _account(db, 102, "TARGET")
    evidence = _fact(db, source, 201)
    name = _name(db, source, 202)
    actor = _actor(db)
    payload = _payload(db, source, target, evidence, action_type)
    proposal = _proposal(db, source, target, evidence, payload, action_type=action_type)
    return source, target, evidence, name, actor, proposal


def test_pairwise_merge_executes_all_roots_and_is_idempotent(db):
    source, target, _evidence, name, actor, proposal = _seed(db)

    result = execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key="a" * 64,
    )

    assert result.proposal_id == proposal.id
    assert result.affected_customer_ids == (source.id, target.id)
    assert result.open_proposal_plan == {"redirect": [], "supersede": []}
    assert source.record_status == "merged"
    assert source.merged_into_customer_id == target.id
    assert source.current_profile_version_id is None
    assert target.current_profile_version_id is None
    assert source.profile_input_seq == 4
    assert target.profile_input_seq == 4
    assert proposal.status == "executed"
    assert models.CustomerObjectOwnership.__table__.primary_key is not None
    owner = db.get(models.CustomerObjectOwnership, ("name", name.id))
    assert owner.current_customer_id == target.id
    assert db.query(models.CustomerEvent).count() == 2

    repeated = execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key="a" * 64,
    )
    assert repeated == result
    assert db.query(models.CustomerEvent).count() == 2
    db.commit()

    with pytest.raises(OwnershipExecutionError) as mismatch:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="z" * 64,
        )
    assert mismatch.value.error_code == "OWNERSHIP_EXECUTION_KEY_MISMATCH"
    assert db.query(models.CustomerEvent).count() == 2


def test_merge_executes_with_evidence_stored_on_third_customer_but_logically_owned(db):
    source = _account(db, 111, "LOGICAL-SOURCE")
    target = _account(db, 112, "LOGICAL-TARGET")
    storage = _account(db, 113, "HISTORICAL-STORAGE")
    evidence = _fact(db, storage, 211)
    actor = _actor(db)
    history = models.CustomerChangeProposal(
        id=811, customer_id=storage.id, target_customer_id=source.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=storage.current_profile_version_id,
        evidence_fact_ids=[evidence.id], risk_level="critical",
        data_classification="restricted_internal", visibility_scope="management",
        action_hash=f"{811:064x}", status="executed",
        expires_at=NOW + timedelta(days=1), created_at=NOW, updated_at=NOW,
    )
    db.add(history)
    db.flush()
    db.add(models.CustomerObjectOwnership(
        object_type="fact", object_id=evidence.id,
        storage_customer_id=storage.id, current_customer_id=source.id,
        ownership_version=1, last_change_proposal_id=history.id,
        last_action_type="split", created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    proposal = _proposal(
        db, source, target, evidence, payload, row_id=812,
    )

    execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key="l" * 64,
    )

    owner = db.get(models.CustomerObjectOwnership, ("fact", evidence.id))
    assert evidence.customer_id == storage.id
    assert owner.current_customer_id == target.id


def test_execution_rejects_stale_inventory_before_any_write(db):
    source, _target, _evidence, _name_row, actor, proposal = _seed(db)
    _name(db, source, 203)
    source_id, proposal_id = source.id, proposal.id
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="b" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_INVENTORY_STALE"
    assert db.get(models.CustomerAccount, source_id).record_status == "active"
    assert db.get(models.CustomerChangeProposal, proposal_id).status == "approved"
    assert db.query(models.CustomerObjectOwnership).count() == 0


def test_split_requires_existing_active_target_and_explicit_retain_source(db):
    source, target, _evidence, _name_row, actor, proposal = _seed(db, "split")
    target.record_status = "archived"
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="c" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_TARGET_INVALID"
    assert db.query(models.CustomerAccount).count() == 2


def test_incomplete_transition_plan_and_different_idempotency_key_fail_closed(db):
    source, target, evidence, _name_row, actor, proposal = _seed(db)
    assignment = models.CustomerAssignment(
        id=301, customer_id=source.id, user_id=actor.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=NOW,
        change_reason="seed", operated_by=actor.id, created_at=NOW, updated_at=NOW,
    )
    db.add(assignment)
    db.flush()
    payload = _payload(db, source, target, evidence)
    action_hash = canonical_action_hash(
        action_type="merge", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = action_hash
    proposal.approved_action_hash = action_hash
    proposal_id = proposal.id
    db.commit()

    with pytest.raises(OwnershipExecutionError) as incomplete:
        execute_customer_ownership_change(
            db, proposal_id=proposal_id, actor_user_id=actor.id,
            idempotency_key="d" * 64,
        )
    assert incomplete.value.error_code == "OWNERSHIP_EXECUTION_TRANSITION_PLAN_INCOMPLETE"


def test_assignment_plan_ends_and_rebuilds_current_primary(db):
    source, target, evidence, _name_row, actor, proposal = _seed(db)
    db.add(models.CustomerAssignment(
        id=301, customer_id=source.id, user_id=actor.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=NOW,
        change_reason="seed", operated_by=actor.id, created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    payload["transition_plan"]["assignments"] = {
        "source_ids": [301],
        "rebuilds": [{"source_id": 301, "new_id": 302, "target_customer_id": target.id}],
    }
    action_hash = canonical_action_hash(
        action_type="merge", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash

    execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key="e" * 64,
    )

    old = db.get(models.CustomerAssignment, 301)
    rebuilt = db.get(models.CustomerAssignment, 302)
    assert old.assignment_status == "ended"
    assert old.effective_to is not None
    assert rebuilt.customer_id == target.id
    assert rebuilt.assignment_status == "active"


def test_split_dnc_plan_defaults_to_every_resulting_customer(db):
    source, target, evidence, _name_row, actor, proposal = _seed(db, "split")
    db.add(models.CustomerAnnotation(
        id=401, customer_id=source.id, annotation_type="do_not_contact",
        content_schema_version="v1", content_json={"reason": "request"},
        policy_scope_type="global", policy_effective_at=NOW,
        visibility="management", data_classification="restricted_internal",
        status="active", authored_by=actor.id, created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    payload = _payload(db, source, target, evidence, "split")
    payload["transition_plan"]["dnc"] = {
        "source_ids": [401],
        "rebuilds": [{"source_id": 401, "new_id": 402, "target_customer_id": target.id}],
    }
    action_hash = canonical_action_hash(
        action_type="split", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="f" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_TRANSITION_PLAN_INCOMPLETE"
    assert db.get(models.CustomerAnnotation, 401).status == "active"

    source = db.get(models.CustomerAccount, 101)
    target = db.get(models.CustomerAccount, 102)
    evidence = db.get(models.CustomerFact, 201)
    proposal = db.get(models.CustomerChangeProposal, 801)
    payload = _payload(db, source, target, evidence, "split")
    payload["transition_plan"]["dnc"] = {
        "source_ids": [401],
        "rebuilds": [
            {"source_id": 401, "new_id": 402, "target_customer_id": source.id},
            {"source_id": 401, "new_id": 403, "target_customer_id": target.id},
        ],
    }
    action_hash = canonical_action_hash(
        action_type="split", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash
    execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=901,
        idempotency_key="j" * 64,
    )
    assert db.get(models.CustomerAnnotation, 401).status == "revoked"
    assert {db.get(models.CustomerAnnotation, row_id).customer_id for row_id in (402, 403)} == {
        source.id, target.id,
    }


def test_redirect_plan_must_reference_a_live_affected_proposal(db):
    source, target, evidence, _name_row, actor, proposal = _seed(db)
    payload = _payload(db, source, target, evidence)
    payload["proposal_redirects"] = [{"proposal_id": 999999, "target_customer_id": target.id}]
    action_hash = canonical_action_hash(
        action_type="merge", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="g" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_REDIRECT_PLAN_INVALID"
    assert db.get(models.CustomerAccount, source.id).record_status == "active"


def test_target_profile_input_sequence_is_revalidated_under_lock(db):
    source, target, _evidence, _name_row, actor, proposal = _seed(db)
    target.profile_input_seq += 1
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="h" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_PROFILE_STALE"


def test_split_partition_may_explicitly_retain_one_root_on_source(db):
    source, target, evidence, name, actor, proposal = _seed(db, "split")
    payload = _payload(db, source, target, evidence, "split")
    retained = next(
        item for item in payload["ownership_partitions"]
        if item["object_type"] == "fact" and item["object_id"] == evidence.id
    )
    retained["target_customer_id"] = source.id
    action_hash = canonical_action_hash(
        action_type="split", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash

    execute_customer_ownership_change(
        db, proposal_id=proposal.id, actor_user_id=actor.id,
        idempotency_key="i" * 64,
    )

    fact_owner = db.get(models.CustomerObjectOwnership, ("fact", evidence.id))
    name_owner = db.get(models.CustomerObjectOwnership, ("name", name.id))
    assert fact_owner.current_customer_id == source.id
    assert name_owner.current_customer_id == target.id


def test_child_evidence_graph_change_invalidates_approved_inventory(db):
    source, target, evidence, _name_row, actor, proposal = _seed(db)
    source_record = models.CustomerSourceRecord(
        id=501, customer_id=source.id, source_system="manual",
        source_account_key="global", authority_level="manual",
        source_entity_type="company", external_record_id="source-501",
        external_record_key_hash=f"{501:064x}", data_classification="internal_business",
        visibility_scope="management", classification_reason="test",
        payload_schema_version="manual_v1", payload_json={}, content_hash=f"{502:064x}",
        captured_at=NOW, processing_status="processed", created_at=NOW,
    )
    db.add(source_record)
    db.flush()
    payload = _payload(db, source, target, evidence)
    action_hash = canonical_action_hash(
        action_type="merge", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash
    db.add(models.CustomerFactEvidenceLink(
        id=502, customer_id=source.id, fact_id=evidence.id, relation_type="supports",
        evidence_kind="source_record", source_record_id=source_record.id,
        evidence_content_hash=source_record.content_hash, locator_json={"json_path": "$"},
        data_classification="internal_business", evidence_fingerprint=f"{503:064x}",
        created_at=NOW,
    ))
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="k" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_INVENTORY_STALE"
    assert db.get(models.CustomerFactEvidenceLink, 502) is not None


def test_conflicting_strong_or_primary_identities_block_execution(db):
    source, target, evidence, _name_row, actor, proposal = _seed(db)
    for row_id, customer, value in (
        (601, source, "company-source"),
        (602, target, "company-target"),
    ):
        db.add(models.CustomerExternalIdentity(
            id=row_id, customer_id=customer.id, source_system="registry",
            source_account_key="global", identifier_type="business_id",
            raw_value=value, normalized_value=value, identity_strength="strong",
            cardinality="one_to_one", auto_match_ceiling="verified",
            verification_status="verified", confidence=1,
            confidence_method_version="test_v1", confidence_components_json={},
            is_primary=True, status="active", identity_fingerprint=f"{row_id:064x}",
            first_seen_at=NOW, last_seen_at=NOW, created_at=NOW, updated_at=NOW,
        ))
    db.flush()
    payload = _payload(db, source, target, evidence)
    action_hash = canonical_action_hash(
        action_type="merge", customer_id=source.id, target_customer_id=target.id,
        payload_json=payload, profile_version_id=source.current_profile_version_id,
        evidence_fact_ids=[evidence.id],
    )
    proposal.payload_json = payload
    proposal.action_hash = proposal.approved_action_hash = action_hash
    db.commit()

    with pytest.raises(OwnershipExecutionError) as raised:
        execute_customer_ownership_change(
            db, proposal_id=proposal.id, actor_user_id=actor.id,
            idempotency_key="l" * 64,
        )

    assert raised.value.error_code == "OWNERSHIP_EXECUTION_IDENTITY_CONFLICT"
