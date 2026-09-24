"""PCW-02 客户档案普通修订与 AI 建议审核契约测试。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.models import CustomerAnnotation, CustomerFact, CustomerProfileVersion
from app.customer.pcw_models import CustomerFactReview
from app.customer.pcw_profile_service import (
    create_private_note,
    create_profile_revision,
    decide_suggestion,
    list_private_notes,
    list_profile_revisions,
    list_profile_suggestions,
)
from tests.test_customer_workflow import _account, _grant_permission, _user

NOW = beijing_now().replace(microsecond=0)


def _customer(db):
    account, version = _account(db, code="C-PCW-REV")
    user = _user(db, 9201)
    for code_value in ("customer:read", "customer_pcw:read", "customer_profile:write"):
        _grant_permission(db, user.id, code_value)
    from app.customer.models import CustomerAssignment

    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=user.id,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=user.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    return account, version, user


def _candidate_fact(db, account, *, fact_key="preference.expressed.color",
                    value="#1B", layer="expressed", status="candidate"):
    row = CustomerFact(
        customer_id=account.id,
        subject_type="customer",
        fact_key=fact_key,
        value_type="string",
        value_json={"value": value},
        fact_layer=layer,
        verification_status=status,
        confidence=0.4,
        confidence_method_version="confidence_v1",
        confidence_components_json={},
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test candidate",
        evidence_json={"source_record_ids": [], "message_ids": [], "order_ids": [], "fact_ids": []},
        rule_version="pcw_test_v1",
        fact_fingerprint=f"{abs(hash((account.id, fact_key, value, len(str(status))))) % (10 ** 20):064x}",
        observed_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def test_revision_rejects_governed_and_unregistered_fields(db):
    account, _version, user = _customer(db)
    for field_key, code in (
        ("identity.legal_name", "GOVERNED_FIELD_REQUIRED"),
        ("ownership.primary_owner", "GOVERNED_FIELD_REQUIRED"),
        ("policy.dnc", "GOVERNED_FIELD_REQUIRED"),
        ("made.up.field", "FIELD_NOT_EDITABLE"),
    ):
        with pytest.raises(pcw_errors.PcwError) as excinfo:
            create_profile_revision(
                db,
                customer_id=account.id,
                actor_user_id=user.id,
                expected_profile_version_id=account.current_profile_version_id,
                expected_profile_input_seq=account.profile_input_seq,
                field_key=field_key,
                value_type="string",
                value="x",
                reason="测试",
            )
        assert excinfo.value.error_code == code


def test_revision_publishes_overlay_and_preserves_source_facts(db):
    account, version, user = _customer(db)
    fact = _candidate_fact(db, account)
    # 在当前档案版本里预置一条已编译的同字段事实投影（模拟编译产物）
    seeded_profile = dict(version.profile_json)
    preferences = dict(seeded_profile.get("preferences") or {})
    preferences["expressed"] = [{
        "fact_id": fact.id,
        "fact_key": "preference.expressed.color",
        "value": "#1B",
        "fact_layer": "expressed",
        "verification_status": "candidate",
    }]
    seeded_profile["preferences"] = preferences
    version.profile_json = seeded_profile
    db.flush()
    result = create_profile_revision(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        expected_profile_version_id=version.id,
        expected_profile_input_seq=account.profile_input_seq,
        field_key="preference.expressed.color",
        value_type="string",
        value="#1B / #613",
        reason="客户本次确认",
        target_fact_id=fact.id,
        evidence_refs=[{"type": "message", "id": 1}],
    )
    db.commit()
    assert result["revision_annotation_id"] > 0
    assert result["profile_version_id"] != version.id
    assert result["profile_input_seq"] == account.profile_input_seq

    annotation = db.get(CustomerAnnotation, result["revision_annotation_id"])
    content = annotation.content_json
    assert annotation.content_schema_version == "v2"
    assert content["revision_kind"] == "profile_field_revision"
    assert content["value"] == "#1B / #613"
    assert annotation.annotation_type == "correction"

    new_version = db.get(CustomerProfileVersion, result["profile_version_id"])
    expressed = new_version.profile_json["preferences"]["expressed"]
    assert expressed[0]["value"] == "#1B / #613"
    assert expressed[0]["source"] == "manual_revision"
    assert expressed[0]["fact_id"] is None
    # 原事实行不变，仅被标注替代
    db.refresh(fact)
    assert fact.value_json["value"] == "#1B"
    assert any(
        item.get("superseded_by_annotation_id") == result["revision_annotation_id"]
        for item in expressed[1:]
    )


def test_revision_version_conflict_returns_visible_diff(db):
    account, version, user = _customer(db)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_profile_revision(
            db,
            customer_id=account.id,
            actor_user_id=user.id,
            expected_profile_version_id=version.id,
            expected_profile_input_seq=account.profile_input_seq + 5,
            field_key="profile.business_type",
            value_type="string",
            value="Retail chain",
            reason="测试",
        )
    assert excinfo.value.error_code == "PROFILE_VERSION_CONFLICT"
    details = excinfo.value.details
    assert details["current_version_id"] == version.id
    assert details["current_input_seq"] == account.profile_input_seq
    assert isinstance(details["visible_diff"], list)


def test_supersede_old_revision(db):
    account, version, user = _customer(db)
    first = create_profile_revision(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        expected_profile_version_id=version.id,
        expected_profile_input_seq=account.profile_input_seq,
        field_key="preference.expressed.length",
        value_type="string",
        value="16 inch",
        reason="首次确认",
    )
    second = create_profile_revision(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        expected_profile_version_id=first["profile_version_id"],
        expected_profile_input_seq=first["profile_input_seq"],
        field_key="preference.expressed.length",
        value_type="string",
        value="18 inch",
        reason="客户变更",
        supersedes_annotation_id=first["revision_annotation_id"],
    )
    db.commit()
    old = db.get(CustomerAnnotation, first["revision_annotation_id"])
    assert old.status == "revoked"
    history = list_profile_revisions(db, customer_id=account.id, actor_user_id=user.id)
    assert history["items"][0]["annotation_id"] == second["revision_annotation_id"]
    assert history["total"] == 2


def test_suggestion_decisions_accept_edit_accept_reject_defer(db):
    account, version, user = _customer(db)
    fact = _candidate_fact(db, account)
    review = CustomerFactReview(
        candidate_fact_id=fact.id,
        customer_id=account.id,
        status="pending",
        suggestion_version=1,
    )
    db.add(review)
    db.flush()

    # reject 必填原因
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_suggestion(
            db, review_id=review.id, actor_user_id=user.id,
            operation="reject", expected_suggestion_version=1,
        )
    assert excinfo.value.error_code == "DECISION_REASON_REQUIRED"

    # defer 必填未来日期
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_suggestion(
            db, review_id=review.id, actor_user_id=user.id,
            operation="defer", expected_suggestion_version=1,
        )
    assert excinfo.value.error_code == "DEFER_UNTIL_REQUIRED"

    deferred = decide_suggestion(
        db, review_id=review.id, actor_user_id=user.id,
        operation="defer", expected_suggestion_version=1,
        defer_until=NOW + timedelta(days=3),
        reason="等客户回复",
    )
    assert deferred["status"] == "deferred"

    # 版本不符 409
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_suggestion(
            db, review_id=review.id, actor_user_id=user.id,
            operation="accept", expected_suggestion_version=1,
            expected_profile_version_id=version.id,
            expected_profile_input_seq=account.profile_input_seq,
        )
    assert excinfo.value.error_code == "SUGGESTION_VERSION_CONFLICT"

    # edit_accept：修订值进入档案
    accepted = decide_suggestion(
        db, review_id=review.id, actor_user_id=user.id,
        operation="edit_accept",
        expected_suggestion_version=deferred["suggestion_version"],
        expected_profile_version_id=version.id,
        expected_profile_input_seq=account.profile_input_seq,
        value="#2A",
        reason="已核对消息",
    )
    db.commit()
    assert accepted["status"] == "accepted"
    assert accepted["revision_annotation_id"] > 0
    new_version = db.get(CustomerProfileVersion, accepted["profile_version_id"])
    assert new_version.profile_json["preferences"]["expressed"][0]["value"] == "#2A"

    # 已终态不可再决定
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_suggestion(
            db, review_id=review.id, actor_user_id=user.id,
            operation="reject",
            expected_suggestion_version=accepted["suggestion_version"],
            reason="x",
        )
    assert excinfo.value.error_code == "SUGGESTION_ALREADY_DECIDED"


def test_human_revision_marks_same_field_suggestions_stale(db):
    account, version, user = _customer(db)
    fact_a = _candidate_fact(db, account, value="Blonde")
    fact_b = _candidate_fact(db, account, value="Natural black")
    review_a = CustomerFactReview(candidate_fact_id=fact_a.id, customer_id=account.id, status="pending", suggestion_version=1)
    review_b = CustomerFactReview(candidate_fact_id=fact_b.id, customer_id=account.id, status="pending", suggestion_version=1)
    db.add_all([review_a, review_b])
    db.flush()

    create_profile_revision(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        expected_profile_version_id=version.id,
        expected_profile_input_seq=account.profile_input_seq,
        field_key="preference.expressed.color",
        value_type="string",
        value="#1B",
        reason="人工确认",
    )
    db.commit()
    for review in (review_a, review_b):
        db.refresh(review)
        assert review.status == "stale"

    # stale 建议不能被采纳
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        decide_suggestion(
            db, review_id=review_a.id, actor_user_id=user.id,
            operation="accept", expected_suggestion_version=review_a.suggestion_version,
            expected_profile_version_id=account.current_profile_version_id,
            expected_profile_input_seq=account.profile_input_seq,
        )
    assert excinfo.value.error_code == "SUGGESTION_STALE"


def test_private_notes_are_author_isolated_and_not_in_profile(db):
    account, _version, user = _customer(db)
    other = _user(db, 9202)
    _grant_permission(db, other.id, "customer:read")
    from app.customer.models import CustomerAssignment

    db.add(CustomerAssignment(
        customer_id=account.id,
        user_id=other.id,
        assignment_role="collaborator",
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
        operated_by=other.id,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    created = create_private_note(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        text="客户喜欢下午联系，仅自己可见",
    )
    create_profile_revision(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        expected_profile_version_id=account.current_profile_version_id,
        expected_profile_input_seq=account.profile_input_seq,
        field_key="profile.business_type",
        value_type="string",
        value="Salon",
        reason="公开业务类型",
    )
    db.commit()

    mine = list_private_notes(db, customer_id=account.id, actor_user_id=user.id)
    assert [item["note_id"] for item in mine["items"]] == [created["note_id"]]
    theirs = list_private_notes(db, customer_id=account.id, actor_user_id=other.id)
    assert theirs["items"] == []

    version = db.get(CustomerProfileVersion, account.current_profile_version_id)
    flat = repr(version.profile_json)
    assert "仅自己可见" not in flat
    assert version.profile_json["business"]["business_type"]["value"] == "Salon"


def test_profile_suggestion_listing_masks_management_scope(db):
    account, _version, user = _customer(db)
    fact = _candidate_fact(db, account)
    fact.visibility_scope = "management"
    review = CustomerFactReview(candidate_fact_id=fact.id, customer_id=account.id, status="pending", suggestion_version=1)
    db.add(review)
    db.flush()

    result = list_profile_suggestions(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        actor_permissions=frozenset({"customer_profile:write"}),
    )
    assert result["items"] == []
    assert result["masked_count"] == 1

    admin_view = list_profile_suggestions(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        actor_permissions=frozenset({"customer:admin"}),
    )
    assert len(admin_view["items"]) == 1


def test_value_type_validation(db):
    account, version, user = _customer(db)
    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_profile_revision(
            db,
            customer_id=account.id,
            actor_user_id=user.id,
            expected_profile_version_id=version.id,
            expected_profile_input_seq=account.profile_input_seq,
            field_key="preference.expressed.quantity",
            value_type="string",
            value="many",
            reason="x",
        )
    assert excinfo.value.error_code == "REVISION_VALUE_TYPE_MISMATCH"

    with pytest.raises(pcw_errors.PcwError) as excinfo:
        create_profile_revision(
            db,
            customer_id=account.id,
            actor_user_id=user.id,
            expected_profile_version_id=version.id,
            expected_profile_input_seq=account.profile_input_seq,
            field_key="preference.expressed.price_range",
            value_type="object",
            value={"foo": 1},
            reason="x",
        )
    assert excinfo.value.error_code == "REVISION_VALUE_INVALID"

    ok = create_profile_revision(
        db,
        customer_id=account.id,
        actor_user_id=user.id,
        expected_profile_version_id=version.id,
        expected_profile_input_seq=account.profile_input_seq,
        field_key="preference.expressed.quantity",
        value_type="number",
        value="500",
        reason="量级确认",
    )
    version2 = db.get(CustomerProfileVersion, ok["profile_version_id"])
    assert version2.profile_json["preferences"]["expressed"][0]["value"] == "500"
