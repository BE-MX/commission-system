"""Logical customer ownership overlay contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
import inspect

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError

from app.customer import models, ownership_service
from app.customer.contracts import (
    OBJECT_OWNERSHIP_REGISTRY,
    OBJECT_OWNERSHIP_REGISTRY_VERSION,
)
from app.customer.ownership_service import (
    CustomerOwnershipError,
    CustomerOwnershipRetryRequired,
    compare_and_set_effective_owner,
    effective_customer_id_expression,
    require_effective_owner,
)
from app.customer.ownership_contract_service import (
    OwnershipContractError,
    require_overlay_eligibility,
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


def _rehash(proposal: models.CustomerChangeProposal) -> None:
    from app.customer.proposal_service import canonical_action_hash
    proposal.action_hash = canonical_action_hash(
        action_type=proposal.action_type,
        customer_id=proposal.customer_id,
        target_customer_id=proposal.target_customer_id,
        payload_json=proposal.payload_json,
        profile_version_id=proposal.profile_version_id,
        evidence_fact_ids=list(proposal.evidence_fact_ids or []),
    )
    proposal.approved_action_hash = proposal.action_hash




def test_registry_is_versioned_and_contains_every_approved_root_type():
    assert OBJECT_OWNERSHIP_REGISTRY_VERSION == "customer_object_ownership_v1"
    assert set(OBJECT_OWNERSHIP_REGISTRY) == {
        "name",
        "external_identity",
        "contact_point",
        "source_record",
        "fact",
        "conversation",
        "order",
        "research_task",
        "search_result",
        "opportunity",
        "action",
        "annotation",
        "acquisition_attribution",
    }


def test_registered_root_customer_comments_explain_storage_and_logical_owner():
    root_models = {
        "name": models.CustomerName,
        "external_identity": models.CustomerExternalIdentity,
        "contact_point": models.CustomerContactPoint,
        "source_record": models.CustomerSourceRecord,
        "fact": models.CustomerFact,
        "conversation": models.CustomerConversation,
        "order": models.CustomerOrder,
        "research_task": models.CustomerResearchTask,
        "search_result": models.SearchResult,
        "opportunity": models.CustomerOpportunity,
        "action": models.CustomerAction,
        "annotation": models.CustomerAnnotation,
        "acquisition_attribution": models.CustomerAcquisitionAttribution,
    }

    assert set(root_models) == set(OBJECT_OWNERSHIP_REGISTRY)
    for model in root_models.values():
        comment = model.__table__.c.customer_id.comment
        assert "创建时不可变" in comment
        assert "存储客户ID" in comment
        assert "ark_customer_object_ownerships" in comment


def test_effective_expression_is_coalesce_without_dynamic_table_sql():
    expression = effective_customer_id_expression(
        models.CustomerName.customer_id,
        models.CustomerObjectOwnership.current_customer_id,
    )
    sql = str(select(expression).compile(dialect=mysql.dialect()))

    assert "coalesce(" in sql.casefold()
    assert "ark_customer_names.customer_id" in sql
    assert "ark_customer_object_ownerships.current_customer_id" in sql
    source = inspect.getsource(ownership_service)
    assert "text(" not in source
    assert 'f"SELECT' not in source


def test_registry_eligibility_blocks_active_policy_and_open_research_roots():
    annotation_policy = OBJECT_OWNERSHIP_REGISTRY["annotation"]
    research_policy = OBJECT_OWNERSHIP_REGISTRY["research_task"]
    assert annotation_policy.handling_mode == "overlay"
    assert annotation_policy.eligibility == "non_policy_annotation"
    assert research_policy.handling_mode == "end_and_rebuild_if_open"
    assert research_policy.eligibility == "terminal_research_task"

    with pytest.raises(OwnershipContractError) as dnc:
        require_overlay_eligibility(
            "annotation",
            models.CustomerAnnotation(annotation_type="do_not_contact", status="active"),
        )
    assert dnc.value.error_code == "OWNERSHIP_POLICY_REBUILD_REQUIRED"
    require_overlay_eligibility(
        "annotation",
        models.CustomerAnnotation(annotation_type="do_not_contact", status="revoked"),
    )
    with pytest.raises(OwnershipContractError) as research:
        require_overlay_eligibility(
            "research_task",
            models.CustomerResearchTask(task_status="running"),
        )
    assert research.value.error_code == "OWNERSHIP_RESEARCH_REBUILD_REQUIRED"
    require_overlay_eligibility(
        "research_task",
        models.CustomerResearchTask(task_status="completed"),
    )


def test_expected_zero_duplicate_is_stable_conflict_and_rolls_back(db, monkeypatch):
    storage = _account(db, "C-DUPLICATE-S")
    target = _account(db, "C-DUPLICATE-T")
    name = _name(db, storage, 220)
    proposal = _proposal(db, storage, target, 320, object_id=name.id)
    db.add(models.CustomerObjectOwnership(
        object_type="name",
        object_id=name.id,
        storage_customer_id=storage.id,
        current_customer_id=target.id,
        ownership_version=1,
        last_change_proposal_id=proposal.id,
        last_action_type="merge",
        created_at=NOW,
        updated_at=NOW,
    ))
    db.commit()
    monkeypatch.setattr(ownership_service, "_overlay", lambda *_args, **_kwargs: None)

    with pytest.raises(CustomerOwnershipError) as raised:
        compare_and_set_effective_owner(
            db,
            object_type="name",
            object_id=name.id,
            storage_customer_id=storage.id,
            expected_current_customer_id=storage.id,
            current_customer_id=target.id,
            expected_version=0,
            change_proposal_id=proposal.id,
            action_type="merge",
        )

    assert raised.value.error_code == "OWNERSHIP_VERSION_CONFLICT"
    assert not db.in_transaction()


@pytest.mark.parametrize(
    ("driver_code", "message"),
    [
        (1213, "Deadlock found"),
        (1205, "Lock wait timeout exceeded"),
        ("40001", "Serialization failure"),
    ],
)
def test_retryable_database_error_requires_new_transaction_and_rolls_back(
    db, monkeypatch, driver_code, message,
):
    def deadlock(*_args, **_kwargs):
        raise OperationalError("UPDATE", {}, Exception(driver_code, message))

    monkeypatch.setattr(ownership_service, "_cas", deadlock)
    db.begin()

    with pytest.raises(CustomerOwnershipRetryRequired) as raised:
        compare_and_set_effective_owner(db)

    assert raised.value.error_code == "RETRY_NEW_TRANSACTION"
    assert raised.value.requires_new_transaction is True
    assert not db.in_transaction()


def test_cas_rejects_tampered_or_undeclared_approved_partition(db):
    storage = _account(db, "C-PARTITION-S")
    target = _account(db, "C-PARTITION-T")
    name = _name(db, storage, 250)
    proposal = _proposal(db, storage, target, 350, object_id=name.id)
    proposal.payload_json["ownership_partitions"][0]["object_id"] = name.id + 1

    with pytest.raises(CustomerOwnershipError) as tampered:
        compare_and_set_effective_owner(
            db,
            object_type="name",
            object_id=name.id,
            storage_customer_id=storage.id,
            expected_current_customer_id=storage.id,
            current_customer_id=target.id,
            expected_version=0,
            change_proposal_id=proposal.id,
            action_type="merge",
        )
    assert tampered.value.error_code == "OWNERSHIP_PROPOSAL_ACTION_HASH_INVALID"

    _rehash(proposal)
    with pytest.raises(CustomerOwnershipError) as undeclared:
        compare_and_set_effective_owner(
            db,
            object_type="name",
            object_id=name.id,
            storage_customer_id=storage.id,
            expected_current_customer_id=storage.id,
            current_customer_id=target.id,
            expected_version=0,
            change_proposal_id=proposal.id,
            action_type="merge",
        )
    assert undeclared.value.error_code == "OWNERSHIP_PARTITION_NOT_APPROVED"


def test_partition_scope_and_expected_current_are_exact(db):
    storage = _account(db, "C-EXACT-S")
    target = _account(db, "C-EXACT-T")
    unrelated = _account(db, "C-EXACT-X")
    name = _name(db, storage, 251)
    proposal = _proposal(db, storage, target, 351, object_id=name.id)

    with pytest.raises(CustomerOwnershipError) as current:
        compare_and_set_effective_owner(
            db,
            object_type="name",
            object_id=name.id,
            storage_customer_id=storage.id,
            expected_current_customer_id=target.id,
            current_customer_id=target.id,
            expected_version=0,
            change_proposal_id=proposal.id,
            action_type="merge",
        )
    assert current.value.error_code == "OWNERSHIP_PARTITION_MISMATCH"

    proposal.payload_json["target_customer_ids"] = [unrelated.id]
    proposal.payload_json["ownership_partitions"][0]["target_customer_id"] = unrelated.id
    _rehash(proposal)
    with pytest.raises(CustomerOwnershipError) as scope:
        compare_and_set_effective_owner(
            db,
            object_type="name",
            object_id=name.id,
            storage_customer_id=storage.id,
            expected_current_customer_id=storage.id,
            current_customer_id=unrelated.id,
            expected_version=0,
            change_proposal_id=proposal.id,
            action_type="merge",
        )
    assert scope.value.error_code == "OWNERSHIP_PROPOSAL_SCOPE_INVALID"


def test_cas_action_type_must_match_the_approved_proposal(db):
    storage = _account(db, "C-ACTION-S")
    target = _account(db, "C-ACTION-T")
    name = _name(db, storage, 252)
    proposal = _proposal(db, storage, target, 352, object_id=name.id)

    with pytest.raises(CustomerOwnershipError) as raised:
        compare_and_set_effective_owner(
            db,
            object_type="name",
            object_id=name.id,
            storage_customer_id=storage.id,
            expected_current_customer_id=storage.id,
            current_customer_id=target.id,
            expected_version=0,
            change_proposal_id=proposal.id,
            action_type="split",
        )

    assert raised.value.error_code == "OWNERSHIP_PROPOSAL_ACTION_MISMATCH"


@pytest.mark.parametrize(
    ("operation", "error_code"),
    [
        ("unknown_type", "OWNERSHIP_OBJECT_TYPE_NOT_REGISTERED"),
        ("missing_object", "OWNERSHIP_OBJECT_NOT_FOUND"),
        ("wrong_storage", "OWNERSHIP_PARTITION_MISMATCH"),
        ("stale_version", "OWNERSHIP_VERSION_CONFLICT"),
        ("bad_action", "OWNERSHIP_ACTION_TYPE_INVALID"),
    ],
)
def test_cas_rejects_invalid_inputs_with_stable_codes(db, operation, error_code):
    storage = _account(db, f"C-{operation}-S")
    target = _account(db, f"C-{operation}-T")
    name = _name(db, storage, 400 + len(operation))
    proposed_object_id = 999999 if operation == "missing_object" else name.id
    proposal = _proposal(
        db,
        storage,
        target,
        500 + len(operation),
        object_id=proposed_object_id,
        expected_ownership_version=1 if operation == "stale_version" else 0,
    )
    kwargs = {
        "object_type": "name",
        "object_id": name.id,
        "storage_customer_id": storage.id,
        "expected_current_customer_id": storage.id,
        "current_customer_id": target.id,
        "expected_version": 0,
        "change_proposal_id": proposal.id,
        "action_type": "merge",
    }
    if operation == "unknown_type":
        kwargs["object_type"] = "runtime_table_name"
    elif operation == "missing_object":
        kwargs["object_id"] = 999999
    elif operation == "wrong_storage":
        kwargs["storage_customer_id"] = target.id
    elif operation == "stale_version":
        kwargs["expected_version"] = 1
    else:
        kwargs["action_type"] = "move"

    with pytest.raises(CustomerOwnershipError) as raised:
        compare_and_set_effective_owner(db, **kwargs)
    assert raised.value.error_code == error_code


def test_require_missing_object_uses_stable_error(db):
    with pytest.raises(CustomerOwnershipError) as raised:
        require_effective_owner(db, "order", 999999)
    assert raised.value.error_code == "OWNERSHIP_OBJECT_NOT_FOUND"
