"""Logical customer ownership overlay contracts."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app.customer import models
from app.customer.ownership_service import (
    CustomerOwnershipError,
    ObjectReference,
    compare_and_set_effective_owner,
    get_effective_owner,
    require_effective_owner,
    resolve_effective_owners,
)


NOW = datetime(2026, 8, 30, 9, 0)


def _account(db, code: str) -> models.CustomerAccount:
    row = models.CustomerAccount(
        customer_code=code,
        display_name=code,
        canonical_company_name=f"{code} LLC",
        entity_type="registered_company",
        identity_status="verified",
        relationship_stage="discovered",
        relationship_stage_changed_at=NOW,
        relationship_stage_reason="test_seed",
        record_status="active",
        identity_confidence=1,
        profile_completeness=80,
        profile_input_seq=0,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _proposal(
    db,
    customer: models.CustomerAccount,
    target: models.CustomerAccount,
    proposal_id: int,
    *,
    object_id: int,
    expected_storage_customer_id: int | None = None,
    expected_current_customer_id: int | None = None,
    expected_ownership_version: int = 0,
    action_type: str = "merge",
) -> models.CustomerChangeProposal:
    profile = models.CustomerProfileVersion(
        id=proposal_id + 10_000,
        customer_id=customer.id,
        version_no=proposal_id,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1",
        input_seq=0,
        profile_json={},
        section_hashes={},
        section_data_as_of={},
        evidence_fact_ids=[],
        change_summary={"changes": []},
        compiler_version="test_v1",
        profile_fingerprint=f"{proposal_id + 10_000:064x}",
        compiled_at=NOW,
        created_at=NOW,
    )
    db.add(profile)
    db.flush()
    payload = {
        "ownership_registry_version": "customer_object_ownership_v1",
        "source_customer_id": customer.id,
        "target_customer_ids": [target.id],
        "ownership_partitions": [{
            "object_type": "name",
            "object_id": object_id,
            "expected_storage_customer_id": (
                expected_storage_customer_id or customer.id
            ),
            "expected_current_customer_id": (
                expected_current_customer_id or customer.id
            ),
            "expected_ownership_version": expected_ownership_version,
            "target_customer_id": target.id,
        }],
    }
    from app.customer.proposal_service import canonical_action_hash
    action_hash = canonical_action_hash(
        action_type=action_type,
        customer_id=customer.id,
        target_customer_id=target.id,
        payload_json=payload,
        profile_version_id=profile.id,
        evidence_fact_ids=[],
    )
    row = models.CustomerChangeProposal(
        id=proposal_id,
        action_type=action_type,
        customer_id=customer.id,
        target_customer_id=target.id,
        payload_schema_version=f"customer_{action_type}_v1",
        payload_json=payload,
        evidence_fact_ids=[],
        profile_version_id=profile.id,
        agent_run_id=None,
        risk_level="high",
        data_classification="restricted_internal",
        visibility_scope="management",
        action_hash=action_hash,
        status="approved",
        approved_action_hash=action_hash,
        expires_at=NOW + timedelta(days=30),
        proposed_by=None,
        decided_by=None,
        decided_at=NOW,
        execution_idempotency_key=None,
        executed_by=None,
        executed_at=None,
        error_code=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _name(db, customer: models.CustomerAccount, row_id: int) -> models.CustomerName:
    row = models.CustomerName(
        id=row_id,
        customer_id=customer.id,
        name=f"Name {row_id}",
        normalized_name=f"name {row_id}",
        name_type="legal",
        verification_status="verified",
        confidence=1,
        confidence_method_version="test_v1",
        confidence_components_json={},
        name_fingerprint=f"{row_id:064x}",
        first_seen_at=NOW,
        last_seen_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _contact_point_with_source(
    db,
    storage: models.CustomerAccount,
    current_relation_customer: models.CustomerAccount,
) -> models.CustomerContactPoint:
    source = models.CustomerSourceRecord(
        id=701,
        customer_id=storage.id,
        source_system="alibaba",
        source_account_key="tenant-a",
        authority_level="transactional",
        source_entity_type="contact",
        external_record_id="contact-701",
        external_record_key_hash=f"{701:064x}",
        data_classification="personal_contact",
        visibility_scope="customer_team",
        classification_reason="test",
        payload_schema_version="alibaba_contact_v1",
        payload_json={},
        content_hash=f"{702:064x}",
        captured_at=NOW,
        processing_status="processed",
        created_at=NOW,
    )
    contact = models.CustomerContact(
        id=702,
        display_name="Buyer",
        identity_status="identified",
        confidence=1,
        confidence_method_version="test_v1",
        confidence_components_json={},
        record_status="active",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add_all([source, contact])
    db.flush()
    old_relation = models.CustomerContactRelationship(
        id=703,
        customer_id=storage.id,
        contact_id=contact.id,
        relationship_type="buyer",
        verification_status="identified",
        confidence=1,
        confidence_method_version="test_v1",
        confidence_components_json={},
        effective_from=NOW,
        effective_to=NOW,
        relationship_fingerprint=f"{703:064x}",
        created_at=NOW,
        updated_at=NOW,
    )
    current_relation = models.CustomerContactRelationship(
        id=704,
        customer_id=current_relation_customer.id,
        contact_id=contact.id,
        relationship_type="buyer",
        verification_status="identified",
        confidence=1,
        confidence_method_version="test_v1",
        confidence_components_json={},
        effective_from=NOW,
        relationship_fingerprint=f"{704:064x}",
        created_at=NOW,
        updated_at=NOW,
    )
    point = models.CustomerContactPoint(
        id=705,
        customer_id=None,
        contact_id=contact.id,
        point_type="email",
        raw_value="buyer@example.com",
        normalized_value="buyer@example.com",
        email_domain_type="corporate",
        verification_status="valid",
        contactability_status="allowed",
        is_primary=True,
        data_classification="personal_contact",
        source_record_id=source.id,
        point_fingerprint=f"{705:064x}",
        first_seen_at=NOW,
        last_seen_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add_all([old_relation, current_relation, point])
    db.flush()
    return point








def test_get_batch_and_require_effective_owner_fall_back_to_storage(db):
    storage = _account(db, "C-STORAGE")
    first = _name(db, storage, 101)
    second = _name(db, storage, 102)

    assert get_effective_owner(db, "name", first.id) == storage.id
    assert require_effective_owner(db, "name", second.id) == storage.id
    assert resolve_effective_owners(
        db,
        [ObjectReference("name", first.id), ObjectReference("name", second.id)],
    ) == {
        ObjectReference("name", first.id): storage.id,
        ObjectReference("name", second.id): storage.id,
    }


def test_batch_resolution_is_set_based_per_registered_object_type(db):
    storage = _account(db, "C-BATCH")
    names = [_name(db, storage, 110 + offset) for offset in range(4)]
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        resolved = resolve_effective_owners(
            db,
            [ObjectReference("name", row.id) for row in names],
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)

    assert set(resolved.values()) == {storage.id}
    assert len(statements) == 2


def test_subject_owned_object_uses_immutable_source_storage_customer(db):
    storage = _account(db, "C-SUBJECT-STORAGE")
    current_relation_customer = _account(db, "C-SUBJECT-CURRENT")
    point = _contact_point_with_source(db, storage, current_relation_customer)

    assert get_effective_owner(db, "contact_point", point.id) == storage.id
    assert resolve_effective_owners(
        db,
        [ObjectReference("contact_point", point.id)],
    ) == {ObjectReference("contact_point", point.id): storage.id}


def test_subject_with_source_never_falls_back_to_contact_relationship(db):
    storage = _account(db, "C-SOURCE-UNRESOLVED")
    relation_customer = _account(db, "C-SOURCE-RELATION")
    point = _contact_point_with_source(db, storage, relation_customer)
    db.get(models.CustomerSourceRecord, point.source_record_id).customer_id = None
    db.flush()

    with pytest.raises(CustomerOwnershipError) as raised:
        require_effective_owner(db, "contact_point", point.id)

    assert raised.value.error_code == "OWNERSHIP_STORAGE_CUSTOMER_UNRESOLVED"


def test_existing_subject_overlay_uses_frozen_storage_not_mutable_relations(db):
    storage = _account(db, "C-FROZEN-STORAGE")
    target = _account(db, "C-FROZEN-TARGET")
    point = _contact_point_with_source(db, storage, target)
    proposal = _proposal(db, storage, target, 360, object_id=999)
    db.add(models.CustomerObjectOwnership(
        object_type="contact_point",
        object_id=point.id,
        storage_customer_id=storage.id,
        current_customer_id=target.id,
        ownership_version=1,
        last_change_proposal_id=proposal.id,
        last_action_type="merge",
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    db.get(models.CustomerSourceRecord, point.source_record_id).customer_id = target.id
    db.flush()

    assert get_effective_owner(db, "contact_point", point.id) == target.id
    assert resolve_effective_owners(
        db,
        [ObjectReference("contact_point", point.id)],
    )[ObjectReference("contact_point", point.id)] == target.id


def test_first_subject_overlay_requires_one_current_effective_relation(db):
    storage = _account(db, "C-AMBIGUOUS-S")
    target = _account(db, "C-AMBIGUOUS-T")
    point = _contact_point_with_source(db, storage, target)
    point.source_record_id = None
    db.get(models.CustomerContactRelationship, 703).effective_to = None
    db.flush()

    with pytest.raises(CustomerOwnershipError) as ambiguous:
        require_effective_owner(db, "contact_point", point.id)
    assert ambiguous.value.error_code == "OWNERSHIP_STORAGE_CUSTOMER_AMBIGUOUS"




def test_cas_creates_overlay_then_retains_row_when_returning_to_storage(db):
    storage = _account(db, "C-STORAGE")
    target = _account(db, "C-TARGET")
    name = _name(db, storage, 201)
    merge = _proposal(db, storage, target, 301, object_id=name.id)

    moved = compare_and_set_effective_owner(
        db,
        object_type="name",
        object_id=name.id,
        storage_customer_id=storage.id,
        expected_current_customer_id=storage.id,
        current_customer_id=target.id,
        expected_version=0,
        change_proposal_id=merge.id,
        action_type="merge",
    )
    assert moved.ownership_version == 1
    assert moved.storage_customer_id == storage.id
    assert moved.current_customer_id == target.id
    assert get_effective_owner(db, "name", name.id) == target.id

    split = _proposal(
        db,
        target,
        storage,
        302,
        object_id=name.id,
        expected_storage_customer_id=storage.id,
        expected_current_customer_id=target.id,
        expected_ownership_version=1,
        action_type="split",
    )
    returned = compare_and_set_effective_owner(
        db,
        object_type="name",
        object_id=name.id,
        storage_customer_id=storage.id,
        expected_current_customer_id=target.id,
        current_customer_id=storage.id,
        expected_version=1,
        change_proposal_id=split.id,
        action_type="split",
    )
    assert returned.ownership_version == 2
    assert returned.current_customer_id == storage.id
    assert db.get(models.CustomerObjectOwnership, ("name", name.id)) is returned
















def test_overlay_model_has_required_constraints_indexes_and_real_comments():
    table = models.CustomerObjectOwnership.__table__
    assert tuple(column.name for column in table.primary_key.columns) == (
        "object_type",
        "object_id",
    )
    assert table.comment
    assert all(column.comment for column in table.c)
    assert {index.name for index in table.indexes} == {
        "ix_customer_object_owner_storage",
        "ix_customer_object_owner_current",
        "ix_customer_object_owner_proposal",
    }
    checks = {constraint.name: str(constraint.sqltext) for constraint in table.constraints if constraint.__class__.__name__ == "CheckConstraint"}
    assert "ownership_version > 0" in checks["ck_customer_object_owner_version"]
    assert "last_action_type IN ('merge', 'split')" in checks[
        "ck_customer_object_owner_action"
    ]


def test_cross_logical_customer_links_use_entity_fks_not_storage_customer_pairs():
    opportunity = models.CustomerOpportunity.__table__
    action = models.CustomerAction.__table__

    def signatures(table):
        return {
            (
                tuple(element.parent.name for element in constraint.elements),
                tuple(element.target_fullname for element in constraint.elements),
                constraint.ondelete,
            )
            for constraint in table.foreign_key_constraints
        }

    assert (("linked_order_id",), ("ark_customer_orders.id",), "RESTRICT") in signatures(opportunity)
    assert (("opportunity_id",), ("ark_customer_opportunities.id",), "RESTRICT") in signatures(action)
    assert (("profile_version_id",), ("ark_customer_profile_versions.id",), "RESTRICT") in signatures(action)
    assert not any(columns == ("linked_order_id", "customer_id") for columns, _, _ in signatures(opportunity))
    assert not any(columns == ("opportunity_id", "customer_id") for columns, _, _ in signatures(action))
    assert not any(columns == ("profile_version_id", "customer_id") for columns, _, _ in signatures(action))
