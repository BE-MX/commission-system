"""Customer reads use current logical ownership after merge and split."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.auth.models import ArkUser
from app.customer import models
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.fact_service import append_source_record
from app.customer.profile_service import _build_context, _build_profile, _load_snapshot
from app.customer.logical_customer_service import logical_root_query
from app.customer.query_service import get_customer, list_opportunities, list_timeline
from app.insight.customer_source_service import get_source_records


NOW = datetime(2026, 8, 31, 10, 0)


def _account(db, row_id: int, code: str, *, status: str = "active", merged_into=None):
    row = models.CustomerAccount(
        id=row_id,
        customer_code=code,
        display_name=code,
        canonical_company_name=f"{code} LLC",
        entity_type="registered_company",
        identity_status="verified",
        relationship_stage="discovered",
        relationship_stage_changed_at=NOW,
        relationship_stage_reason="test",
        record_status=status,
        merged_into_customer_id=merged_into,
        identity_confidence=Decimal("1"),
        profile_completeness=Decimal("0"),
        profile_input_seq=1,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _assignment(db, customer_id: int, user_id: int):
    db.add(models.CustomerAssignment(
        customer_id=customer_id,
        user_id=user_id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()


def _user(db, row_id: int):
    row = ArkUser(
        id=row_id,
        username=f"logical-{row_id}",
        password_hash="x",
        real_name=f"Logical {row_id}",
        is_active=True,
        must_change_password=False,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _identity(user_id: int):
    return {"sub": str(user_id), "roles": [], "permissions": ["customer:read"]}


def _name(db, customer_id: int, row_id: int, value: str):
    row = models.CustomerName(
        id=row_id,
        customer_id=customer_id,
        name=value,
        normalized_name=value.casefold(),
        name_type="legal",
        verification_status="verified",
        confidence=Decimal("1"),
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


def _fact(db, customer_id: int, row_id: int, value: str):
    row = models.CustomerFact(
        id=row_id,
        customer_id=customer_id,
        subject_type="customer",
        fact_key="business.industry",
        fact_layer="confirmed",
        value_type="string",
        value_json={"value": value},
        verification_status="verified",
        confidence=Decimal("1"),
        confidence_method_version="test_v1",
        confidence_components_json={},
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test",
        evidence_json={},
        fact_fingerprint=f"{row_id:064x}",
        observed_at=NOW,
        created_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _move(db, object_type: str, row, storage_id: int, target_id: int, proposal_id: int):
    db.add(models.CustomerObjectOwnership(
        object_type=object_type,
        object_id=row.id,
        storage_customer_id=storage_id,
        current_customer_id=target_id,
        ownership_version=1,
        last_change_proposal_id=proposal_id,
        last_action_type="merge",
        created_at=NOW,
        updated_at=NOW,
    ))


def _proposal_stub(db, source_id: int, target_id: int, row_id: int):
    profile = models.CustomerProfileVersion(
        id=row_id + 1,
        customer_id=source_id,
        version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1",
        input_seq=1,
        profile_json={},
        section_hashes={},
        section_data_as_of={},
        evidence_fact_ids=[],
        change_summary={},
        compiler_version="test_v1",
        profile_fingerprint=f"{row_id + 1:064x}",
        compiled_at=NOW,
        created_at=NOW,
    )
    db.add(profile)
    db.flush()
    row = models.CustomerChangeProposal(
        id=row_id,
        customer_id=source_id,
        target_customer_id=target_id,
        action_type="merge",
        payload_schema_version="customer_merge_v1",
        payload_json={},
        evidence_fact_ids=[],
        profile_version_id=profile.id,
        risk_level="critical",
        data_classification="restricted_internal",
        visibility_scope="management",
        action_hash=f"{row_id:064x}",
        expires_at=NOW + timedelta(days=1),
        status="executed",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def test_merged_alias_reauthorizes_against_canonical_customer(db):
    source_owner = _user(db, 1101)
    target_owner = _user(db, 1102)
    target = _account(db, 1202, "TARGET")
    source = _account(db, 1201, "SOURCE", status="merged", merged_into=target.id)
    _assignment(db, source.id, source_owner.id)
    _assignment(db, target.id, target_owner.id)

    with pytest.raises(CustomerAccessDenied):
        require_customer_access(
            db,
            customer_id=source.id,
            user=_identity(source_owner.id),
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
        )

    detail = get_customer(db, _identity(target_owner.id), source.id)
    assert detail["customer_id"] == target.id
    assert detail["display_name"] == "TARGET"


def test_profile_snapshot_uses_effective_root_owner_and_split_isolation(db):
    left = _account(db, 1301, "LEFT")
    right = _account(db, 1302, "RIGHT")
    proposal = _proposal_stub(db, left.id, right.id, 1399)
    left_name = _name(db, left.id, 1311, "Left Brand")
    moved_name = _name(db, left.id, 1312, "Right Brand")
    left_fact = _fact(db, left.id, 1321, "retail")
    moved_fact = _fact(db, left.id, 1322, "wholesale")
    _move(db, "name", moved_name, left.id, right.id, proposal.id)
    _move(db, "fact", moved_fact, left.id, right.id, proposal.id)
    db.flush()

    left_snapshot = _load_snapshot(db, left, NOW)
    right_snapshot = _load_snapshot(db, right, NOW)

    assert {item["name"] for item in left_snapshot.names} == {left_name.name}
    assert {item["name"] for item in right_snapshot.names} == {moved_name.name}
    assert {item["id"] for item in left_snapshot.facts} == {left_fact.id}
    assert {item["id"] for item in right_snapshot.facts} == {moved_fact.id}


def test_timeline_keeps_account_events_and_does_not_move_source_history(db):
    reader = _user(db, 1401)
    target = _account(db, 1402, "TARGET")
    source = _account(db, 1403, "SOURCE", status="merged", merged_into=target.id)
    _assignment(db, target.id, reader.id)
    db.add_all([
        models.CustomerEvent(
            customer_id=source.id,
            event_type="source.old",
            event_source="manual",
            event_title="old source event",
            event_summary="must stay on source",
            event_payload={},
            importance="normal",
            data_classification="internal_business",
            visibility_scope="customer_team",
            classification_reason="test",
            evidence_fact_ids=[],
            event_fingerprint="a" * 64,
            occurred_at=NOW,
            created_at=NOW,
        ),
        models.CustomerEvent(
            customer_id=target.id,
            event_type="customer.merged",
            event_source="system",
            event_title="merge summary",
            event_summary="source merged into target",
            event_payload={},
            importance="high",
            data_classification="internal_business",
            visibility_scope="customer_team",
            classification_reason="test",
            evidence_fact_ids=[],
            event_fingerprint="b" * 64,
            occurred_at=NOW,
            created_at=NOW,
        ),
    ])
    db.flush()

    rows, total = list_timeline(
        db, _identity(reader.id), source.id, page=1, page_size=20,
    )
    assert total == 1
    assert [item["event_type"] for item in rows] == ["customer.merged"]


def test_opportunity_list_scopes_and_serializes_by_effective_owner(db):
    reader = _user(db, 1501)
    storage = _account(db, 1502, "STORAGE")
    logical = _account(db, 1503, "LOGICAL")
    _assignment(db, logical.id, reader.id)
    proposal = _proposal_stub(db, storage.id, logical.id, 1590)
    opportunity = models.CustomerOpportunity(
        id=1510,
        customer_id=storage.id,
        opportunity_type="inquiry",
        source="manual",
        source_system="manual",
        source_account_key="global",
        source_key="logical-opportunity",
        priority_level="A",
        confidence_score=Decimal("80"),
        urgency="high",
        title="Moved opportunity",
        product_requirement_json={},
        competitor_json={},
        evidence_fact_ids=[],
        status="pending",
        stage_entered_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(opportunity)
    db.flush()
    _move(db, "opportunity", opportunity, storage.id, logical.id, proposal.id)
    db.flush()

    items, total = list_opportunities(
        db,
        {
            "sub": str(reader.id),
            "roles": [],
            "permissions": ["customer_opportunity:read"],
        },
        page=1,
        page_size=20,
    )

    assert total == 1
    assert items == [{
        "opportunity_id": opportunity.id,
        "customer_id": logical.id,
        "title": "Moved opportunity",
        "status": "pending",
        "priority_level": "A",
        "owner_user_id": None,
        "due_at": None,
        "updated_at": NOW.replace(tzinfo=None).isoformat() + "+08:00",
    }]


def test_profile_snapshot_projects_logical_opportunities_and_actions(db):
    storage = _account(db, 1601, "STORAGE")
    logical = _account(db, 1602, "LOGICAL")
    proposal = _proposal_stub(db, storage.id, logical.id, 1690)
    opportunity = models.CustomerOpportunity(
        id=1610, customer_id=storage.id, opportunity_type="inquiry", source="manual",
        source_system="manual", source_account_key="global", source_key="profile-opp",
        priority_level="A", confidence_score=Decimal("80"), urgency="high",
        title="Profile opportunity", product_requirement_json={}, competitor_json={},
        evidence_fact_ids=[], status="pending", stage_entered_at=NOW,
        created_at=NOW, updated_at=NOW,
    )
    db.add(opportunity)
    db.flush()
    profile = db.get(models.CustomerProfileVersion, 1691)
    action = models.CustomerAction(
        id=1620, customer_id=storage.id, opportunity_id=opportunity.id,
        action_type="email", thread_group="new_inquiry", priority="high",
        reason="Reply is due", next_action="Send reply", action_date=NOW.date(),
        status="pending", feedback_json={}, source_event_ids=[], evidence_fact_ids=[],
        profile_version_id=profile.id, source_type="manual", policy_version="test_v1",
        action_fingerprint=f"{1620:064x}", evidence_status="valid",
        generated_at=NOW, created_at=NOW, updated_at=NOW,
    )
    db.add(action)
    db.flush()
    _move(db, "opportunity", opportunity, storage.id, logical.id, proposal.id)
    _move(db, "action", action, storage.id, logical.id, proposal.id)
    db.flush()

    snapshot = _load_snapshot(db, logical, NOW)

    assert snapshot.opportunities == ({
        "id": opportunity.id,
        "title": opportunity.title,
        "status": opportunity.status,
        "priority_level": opportunity.priority_level,
        "due_at": None,
        "evidence_fact_ids": [],
        "data_classification": "internal_business",
        "visibility_scope": "customer_team",
        "updated_at": NOW,
    },)
    assert snapshot.actions == ({
        "id": action.id,
        "action_type": action.action_type,
        "priority": action.priority,
        "reason": action.reason,
        "next_action": action.next_action,
        "due_at": None,
        "status": "pending",
        "evidence_status": "valid",
        "evidence_fact_ids": [],
        "data_classification": "internal_business",
        "visibility_scope": "customer_team",
        "updated_at": NOW,
    },)
    profile = _build_profile(snapshot, NOW)[0]
    assert [item["id"] for item in profile["opportunities"]["open"]] == [opportunity.id]
    assert [item["id"] for item in profile["recommended_actions"]["items"]] == [action.id]
    version = SimpleNamespace(
        profile_json=profile,
        change_summary={"changes": []},
        version_no=1,
        profile_schema_version="customer_profile_v1",
        compiled_at=NOW,
        section_data_as_of={},
    )
    context = _build_context(version)
    assert [item["id"] for item in context["open_opportunities"]] == [opportunity.id]
    assert [item["id"] for item in context["recommended_actions"]] == [action.id]
    profile["opportunities"]["open"][0]["data_classification"] = "restricted_internal"
    profile["recommended_actions"]["items"][0]["visibility_scope"] = "management"
    restricted_context = _build_context(version)
    assert restricted_context["open_opportunities"] == []
    assert restricted_context["recommended_actions"] == []


def test_contact_owned_root_without_source_fails_closed_when_relationship_is_ambiguous(db):
    first = _account(db, 1701, "FIRST")
    second = _account(db, 1702, "SECOND")
    contact = models.CustomerContact(
        id=1710, display_name="Shared Buyer", identity_status="identified",
        confidence=Decimal("1"), confidence_method_version="test_v1",
        confidence_components_json={}, record_status="active",
        created_at=NOW, updated_at=NOW,
    )
    db.add(contact)
    db.flush()
    for row_id, customer in ((1711, first), (1712, second)):
        db.add(models.CustomerContactRelationship(
            id=row_id, customer_id=customer.id, contact_id=contact.id,
            relationship_type="buyer", verification_status="identified",
            confidence=Decimal("1"), confidence_method_version="test_v1",
            confidence_components_json={}, effective_from=None,
            relationship_fingerprint=f"{row_id:064x}", created_at=NOW, updated_at=NOW,
        ))
    point = models.CustomerContactPoint(
        id=1720, contact_id=contact.id, point_type="email",
        raw_value="shared@example.com", normalized_value="shared@example.com",
        email_domain_type="corporate", verification_status="valid",
        contactability_status="allowed", is_primary=True,
        data_classification="personal_contact", point_fingerprint=f"{1720:064x}",
        first_seen_at=NOW, last_seen_at=NOW, created_at=NOW, updated_at=NOW,
    )
    db.add(point)
    db.flush()

    assert logical_root_query(db, models.CustomerContactPoint, "contact_point", first.id).all() == []
    assert logical_root_query(db, models.CustomerContactPoint, "contact_point", second.id).all() == []


def test_source_drawer_authorizes_and_reads_by_effective_owner(db):
    source_user = _user(db, 1801)
    target_user = _user(db, 1802)
    storage = _account(db, 1810, "STORAGE")
    target = _account(db, 1811, "TARGET")
    _assignment(db, storage.id, source_user.id)
    _assignment(db, target.id, target_user.id)
    proposal = _proposal_stub(db, storage.id, target.id, 1890)
    source_record = append_source_record(
        db, customer_id=storage.id, source_system="public_web",
        source_account_key="global", source_entity_type="company_page",
        external_record_id="logical-drawer", payload_schema_version="company_page_v1",
        payload_json={"name": "Logical Drawer"}, processing_status="processed",
    )
    _move(db, "source_record", source_record, storage.id, target.id, proposal.id)
    db.flush()
    source_access = require_customer_access(
        db, customer_id=storage.id, user=_identity(source_user.id),
        action_permissions={"customer:read"}, manage_permissions={"customer:admin"},
    )
    target_access = require_customer_access(
        db, customer_id=target.id, user=_identity(target_user.id),
        action_permissions={"customer:read"}, manage_permissions={"customer:admin"},
    )

    assert get_source_records(
        db, storage.id, "source_record", access=source_access,
    ) == []
    target_rows = get_source_records(
        db, target.id, "source_record", access=target_access,
    )
    assert [item["source_record_id"] for item in target_rows] == [source_record.id]
