"""Logical customer list reads keep query counts independent of row count."""

from datetime import datetime, timedelta

from sqlalchemy import event

from app.auth.models import ArkUser
from app.customer import models
from app.customer.fact_service import append_source_record
from app.customer.logical_customer_service import (
    logical_root_query,
    resolve_canonical_customer_id,
)
from app.customer.query_service import list_customers, list_research_tasks


NOW = datetime(2026, 8, 31, 8, 0)


def _account(db, code, user_id):
    row = models.CustomerAccount(
        customer_code=code, display_name=code, entity_type="registered_company",
        identity_status="verified", relationship_stage="discovered",
        relationship_stage_changed_at=NOW, relationship_stage_reason="test",
        record_status="active", identity_confidence=1, profile_completeness=0,
        profile_input_seq=0, created_at=NOW, updated_at=NOW,
    )
    db.add(row)
    db.flush()
    db.add(models.CustomerAssignment(
        customer_id=row.id, user_id=user_id, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=NOW,
        created_at=NOW, updated_at=NOW,
    ))
    db.flush()
    return row


def _count_selects(db, callback):
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    return result, len(statements)


def test_customer_list_prefetches_projection_and_primary_marker(db):
    user = ArkUser(id=1901, username="list-count", password_hash="x", real_name="List")
    db.add(user)
    db.flush()
    first = _account(db, "COUNT-A", user.id)
    second = _account(db, "COUNT-B", user.id)
    version = models.CustomerProfileVersion(
        customer_id=first.id, version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1", input_seq=0, profile_json={},
        section_hashes={}, section_data_as_of={}, evidence_fact_ids=[],
        change_summary={}, compiler_version="test",
        profile_fingerprint="a" * 64, compiled_at=NOW, created_at=NOW,
    )
    db.add(version)
    db.flush()
    db.add(models.CustomerListProjection(
        customer_id=first.id, profile_version_id=version.id, compiled_at=NOW,
        commercial_value_score=0, has_valid_order=False, valid_order_count=0,
        valid_order_amount_usd=0, engagement_health="new", open_opportunity_count=0,
        global_claim_blocked=False, has_active_dnc=False, data_quality_score=0,
    ))
    db.flush()

    (rows, total), selects = _count_selects(db, lambda: list_customers(
        db, {"sub": str(user.id), "roles": [], "permissions": ["customer:read"]},
        page=1, page_size=20,
    ))

    assert total == len(rows) == 2
    assert {row["customer_id"] for row in rows} == {first.id, second.id}
    assert selects == 2


def test_research_list_batches_access_for_multiple_customers(db):
    user = ArkUser(id=1951, username="research-count", password_hash="x", real_name="Research")
    db.add(user)
    db.flush()
    customers = [_account(db, f"RESEARCH-{index}", user.id) for index in range(2)]
    for index, customer in enumerate(customers, 1):
        db.add(models.CustomerResearchTask(
            customer_id=customer.id, task_type="company_research", task_status="completed",
            gate_status="passed", result_review_status="accepted",
            selection_reason=[], research_policy_version="v1",
            task_fingerprint=f"{1951 + index:064x}", input_snapshot={},
            data_classification="internal_business", visibility_scope="customer_team",
            classification_reason="test", evidence_fact_ids=[], lease_generation=0,
            attempt_count=0, created_at=NOW, updated_at=NOW,
        ))
    db.flush()

    (rows, total), selects = _count_selects(db, lambda: list_research_tasks(
        db, {
            "sub": str(user.id), "roles": [],
            "permissions": ["sales_automation:read"],
        }, page=1, page_size=20,
    ))

    assert total == len(rows) == 2
    assert {row["customer_id"] for row in rows} == {item.id for item in customers}
    assert selects == 3


def test_canonical_alias_cycle_fails_closed(db):
    user = ArkUser(id=1981, username="cycle", password_hash="x", real_name="Cycle")
    db.add(user)
    db.flush()
    first = _account(db, "CYCLE-A", user.id)
    second = _account(db, "CYCLE-B", user.id)
    first.record_status = second.record_status = "merged"
    first.merged_into_customer_id = second.id
    second.merged_into_customer_id = first.id
    db.flush()

    assert resolve_canonical_customer_id(db, first.id) is None
    assert resolve_canonical_customer_id(db, second.id) is None


def test_source_owned_identity_and_contact_point_follow_source_effective_owner(db):
    user = ArkUser(id=1991, username="source-owned", password_hash="x", real_name="Source")
    db.add(user)
    db.flush()
    storage = _account(db, "SOURCE-OWNED-STORAGE", user.id)
    target = _account(db, "SOURCE-OWNED-TARGET", user.id)
    version = models.CustomerProfileVersion(
        customer_id=storage.id, version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1", input_seq=0, profile_json={},
        section_hashes={}, section_data_as_of={}, evidence_fact_ids=[],
        change_summary={}, compiler_version="test",
        profile_fingerprint="b" * 64, compiled_at=NOW, created_at=NOW,
    )
    db.add(version)
    db.flush()
    proposal = models.CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=version.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="c" * 64,
        status="executed", expires_at=NOW + timedelta(days=1),
    )
    db.add(proposal)
    db.flush()
    source = append_source_record(
        db, customer_id=storage.id, source_system="public_web",
        source_account_key="global", source_entity_type="company_page",
        external_record_id="source-owned", payload_schema_version="company_page_v1",
        payload_json={"company": "Target"}, processing_status="processed",
    )
    identity = models.CustomerExternalIdentity(
        customer_id=storage.id, source_system="web", source_account_key="global",
        identifier_type="website_domain", raw_value="target.example",
        normalized_value="target.example", identity_strength="strong",
        cardinality="one_to_one", auto_match_ceiling="verified",
        verification_status="verified", confidence=1,
        confidence_method_version="test", confidence_components_json={},
        is_primary=True, source_record_id=source.id, first_seen_at=NOW,
        last_seen_at=NOW, status="active", identity_fingerprint="d" * 64,
    )
    point = models.CustomerContactPoint(
        customer_id=storage.id, point_type="website",
        raw_value="https://target.example", normalized_value="target.example",
        verification_status="valid", contactability_status="allowed",
        is_primary=True, data_classification="public_business",
        source_record_id=source.id, point_fingerprint="e" * 64,
        first_seen_at=NOW, last_seen_at=NOW,
    )
    db.add_all([identity, point])
    db.flush()
    db.add(models.CustomerObjectOwnership(
        object_type="source_record", object_id=source.id,
        storage_customer_id=storage.id, current_customer_id=target.id,
        ownership_version=1, last_change_proposal_id=proposal.id,
        last_action_type="split",
    ))
    db.flush()

    assert logical_root_query(
        db, models.CustomerExternalIdentity, "external_identity", storage.id,
    ).all() == []
    assert logical_root_query(
        db, models.CustomerContactPoint, "contact_point", storage.id,
    ).all() == []
    assert logical_root_query(
        db, models.CustomerExternalIdentity, "external_identity", target.id,
    ).one().id == identity.id
    assert logical_root_query(
        db, models.CustomerContactPoint, "contact_point", target.id,
    ).one().id == point.id
