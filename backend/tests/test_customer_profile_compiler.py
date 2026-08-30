"""Versioned customer profile compiler contracts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.time import beijing_now
from app.customer.fact_service import append_customer_event, append_source_record
from app.customer.models import (
    CustomerAccount,
    CustomerAgentContext,
    CustomerAssignment,
    CustomerFact,
    CustomerFactConflict,
    CustomerListProjection,
    CustomerName,
    CustomerProfileVersion,
    CustomerTargetMatch,
)
from app.customer.profile_service import ProfileCompileError, compile_customer_profile
from app.sales_automation.models import AcquisitionProfile


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _customer(db, suffix: str, *, input_seq: int = 1) -> CustomerAccount:
    now = beijing_now()
    row = CustomerAccount(
        customer_code=f"C-{suffix}",
        display_name=f"Buyer {suffix}",
        canonical_company_name=f"{suffix} Hair LLC",
        entity_type="registered_company",
        identity_status="verified",
        relationship_stage="discovered",
        relationship_stage_changed_at=now,
        relationship_stage_reason="test_seed",
        record_status="active",
        primary_country_code="US",
        identity_confidence=Decimal("0.9500"),
        profile_completeness=Decimal("0.00"),
        profile_input_seq=input_seq,
    )
    db.add(row)
    db.flush()
    return row


def _fact(
    db,
    customer: CustomerAccount,
    *,
    key: str,
    value,
    layer: str,
    status: str = "verified",
    classification: str = "internal_business",
    visibility: str = "customer_team",
    observed_at: datetime | None = None,
    expires_at: datetime | None = None,
    fingerprint_suffix: str = "base",
) -> CustomerFact:
    observed_at = observed_at or beijing_now()
    row = CustomerFact(
        customer_id=customer.id,
        subject_type="customer",
        subject_id=None,
        fact_key=key,
        value_type=(
            "boolean" if isinstance(value, bool)
            else "number" if isinstance(value, (int, float, Decimal))
            else "list" if isinstance(value, list)
            else "object" if isinstance(value, dict)
            else "string"
        ),
        value_json={"value": value},
        fact_layer=layer,
        verification_status=status,
        confidence=Decimal("0.9000"),
        confidence_method_version="confidence_v1",
        confidence_components_json={"source_authority": 0.9},
        data_classification=classification,
        visibility_scope=visibility,
        classification_reason="test evidence",
        evidence_json={"source_record_ids": [], "fact_ids": []},
        rule_version="test_v1",
        fact_fingerprint=_digest(
            f"{customer.id}|{key}|{layer}|{value!r}|{observed_at.isoformat()}|{fingerprint_suffix}"
        ),
        observed_at=observed_at,
        expires_at=expires_at,
    )
    db.add(row)
    customer.profile_input_seq += 1
    db.flush()
    return row


class _OneShotObserver:
    def __init__(self, phase: str, callback):
        self.phase = phase
        self.callback = callback
        self.fired = False

    def __call__(self, phase, _db, _customer_id, _base_seq):
        if phase == self.phase and not self.fired:
            self.fired = True
            self.callback()


def test_first_compile_publishes_immutable_version_and_current_projections(db):
    customer = _customer(db, "first")
    industry = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair extensions",
        layer="source",
    )

    result = compile_customer_profile(db, customer.id)

    version = db.get(CustomerProfileVersion, result.profile_version_id)
    assert result.created is True
    assert version.version_no == 1
    assert version.input_seq == customer.profile_input_seq
    assert version.profile_json["business"]["industry"]["value"] == "Hair extensions"
    assert version.evidence_fact_ids == [industry.id]
    assert set(version.section_hashes) == {
        "identity", "business", "contacts", "ownership", "engagement",
        "commercial", "preferences", "behavior", "opportunities", "risks",
        "recommended_actions", "quality",
    }
    assert customer.current_profile_version_id == version.id
    assert customer.profile_compiled_at == version.compiled_at
    assert db.get(CustomerAgentContext, customer.id).profile_version_id == version.id
    assert db.get(CustomerListProjection, customer.id).profile_version_id == version.id
    assert result.projections["agent_context"].status == "current"
    assert result.projections["list_projection"].status == "current"


def test_profile_json_converts_business_datetimes_to_canonical_strings(db):
    customer = _customer(db, "json-datetimes")
    now = beijing_now()
    db.add(CustomerName(
        customer_id=customer.id,
        name="JSON Trading",
        normalized_name="json trading",
        name_type="trading",
        verification_status="verified",
        confidence=Decimal("0.9000"),
        confidence_method_version="confidence_v1",
        confidence_components_json={"source_authority": 0.9},
        name_fingerprint=_digest("json-trading-name"),
        first_seen_at=now,
        last_seen_at=now,
    ))
    db.add(CustomerAssignment(
        customer_id=customer.id,
        user_id=987654,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=now,
    ))
    customer.profile_input_seq += 2
    db.flush()

    result = compile_customer_profile(db, customer.id)
    db.flush()

    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    assert profile["identity"]["aliases"][0]["last_seen_at"] == now.isoformat(
        timespec="seconds"
    )
    assert profile["ownership"]["primary_owner_user_id"] == 987654


def test_unbound_referenced_source_still_tightens_alias_classification(db):
    customer = _customer(db, "unbound-source-classification")
    now = beijing_now()
    source = append_source_record(
        db,
        customer_id=None,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="unbound-restricted-alias",
        payload_schema_version="public_company_page_v1",
        payload_json={"name": "Restricted Alias"},
        data_classification="restricted_internal",
        visibility_scope="management",
    )
    db.add(CustomerName(
        customer_id=customer.id,
        name="Restricted Alias",
        normalized_name="restricted alias",
        name_type="trading",
        verification_status="candidate",
        confidence=Decimal("0.7000"),
        confidence_method_version="confidence_v1",
        confidence_components_json={"source_authority": 0.7},
        source_record_id=source.id,
        name_fingerprint=_digest("unbound-restricted-alias"),
        first_seen_at=now,
        last_seen_at=now,
    ))
    customer.profile_input_seq += 1
    db.flush()

    result = compile_customer_profile(db, customer.id)
    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    context = db.get(CustomerAgentContext, customer.id).context_json

    assert profile["identity"]["aliases"][0]["data_classification"] == "restricted_internal"
    assert context["identity"]["aliases"] == []


def test_semantic_no_change_suppresses_new_version_after_irrelevant_seq_bump(db):
    customer = _customer(db, "no-change")
    first = compile_customer_profile(db, customer.id)
    customer.profile_input_seq += 1
    db.flush()

    replay = compile_customer_profile(db, customer.id)

    assert replay.created is False
    assert replay.profile_version_id == first.profile_version_id
    assert db.query(CustomerProfileVersion).filter_by(customer_id=customer.id).count() == 1
    assert replay.projections["target_matches"].status == "current"


def test_no_change_profile_rebuilds_target_match_when_target_policy_changes(db):
    customer = _customer(db, "target-policy-change")
    _fact(
        db,
        customer,
        key="business.industry",
        value="Hair extensions",
        layer="source",
    )
    target = AcquisitionProfile(
        profile_key="policy-change",
        company_name="LeShine",
        products=[],
        advantages=[],
        target_countries=[],
        target_industries=["Hair extensions"],
        target_roles=[],
        exclusions=[],
        status="active",
    )
    db.add(target)
    db.flush()
    first = compile_customer_profile(db, customer.id)
    first_match = db.query(CustomerTargetMatch).filter_by(
        customer_id=customer.id,
        target_profile_id=target.id,
        is_current=True,
    ).one()
    first_fingerprint = first_match.match_fingerprint
    target.target_industries = ["Packaging"]
    db.flush()

    replay = compile_customer_profile(db, customer.id)

    current = db.query(CustomerTargetMatch).filter_by(
        customer_id=customer.id,
        target_profile_id=target.id,
        is_current=True,
    ).one()
    assert replay.created is False
    assert replay.profile_version_id == first.profile_version_id
    assert current.match_fingerprint != first_fingerprint
    assert current.match_score == Decimal("0.00")
    assert replay.projections["target_matches"].status == "current"


def test_archived_customer_is_globally_blocked_in_list_projection(db):
    customer = _customer(db, "archived")
    customer.record_status = "archived"
    customer.profile_input_seq += 1
    db.flush()

    compile_customer_profile(db, customer.id)

    projection = db.get(CustomerListProjection, customer.id)
    assert projection.global_claim_blocked is True
    assert projection.global_claim_block_reason == "record_archived"


def test_list_projection_uses_latest_current_engagement_fact_time(db):
    customer = _customer(db, "last-engagement")
    occurred_at = (beijing_now() - timedelta(days=2)).replace(microsecond=0)
    _fact(
        db,
        customer,
        key="preference.expressed.product_family",
        value="Wigs",
        layer="expressed",
        observed_at=occurred_at,
    )

    compile_customer_profile(db, customer.id)

    assert db.get(CustomerListProjection, customer.id).last_engagement_at == occurred_at


def test_no_change_cas_refreshes_database_value_instead_of_trusting_identity_map(db):
    customer = _customer(db, "database-cas-refresh")
    first = compile_customer_profile(db, customer.id)

    def external_style_seq_bump():
        db.execute(
            text(
                "UPDATE ark_customer_accounts "
                "SET profile_input_seq = profile_input_seq + 1 WHERE id = :customer_id"
            ),
            {"customer_id": customer.id},
            execution_options={"synchronize_session": False},
        )

    result = compile_customer_profile(
        db,
        customer.id,
        observer=_OneShotObserver("before_no_change_cas", external_style_seq_bump),
    )

    assert result.created is False
    assert result.profile_version_id == first.profile_version_id
    assert result.retry_count == 1


def test_no_change_path_rechecks_seq_under_lock_and_rebuilds_new_snapshot(db):
    customer = _customer(db, "no-change-race")
    first = compile_customer_profile(db, customer.id)

    observer = _OneShotObserver(
        "before_no_change_cas",
        lambda: _fact(
            db,
            customer,
            key="business.industry",
            value="Wigs",
            layer="source",
            fingerprint_suffix="race",
        ),
    )
    result = compile_customer_profile(db, customer.id, observer=observer)

    assert observer.fired is True
    assert result.created is True
    assert result.profile_version_id != first.profile_version_id
    assert result.retry_count == 1
    assert db.get(CustomerProfileVersion, result.profile_version_id).profile_json[
        "business"
    ]["industry"]["value"] == "Wigs"


def test_old_snapshot_cannot_publish_after_newer_input_seq(db):
    customer = _customer(db, "publish-race")
    _fact(
        db,
        customer,
        key="business.industry",
        value="Beauty",
        layer="source",
    )
    observer = _OneShotObserver(
        "before_publish_cas",
        lambda: _fact(
            db,
            customer,
            key="preference.expressed.color",
            value="Natural black",
            layer="expressed",
            fingerprint_suffix="newer",
        ),
    )

    result = compile_customer_profile(db, customer.id, observer=observer)

    versions = db.query(CustomerProfileVersion).filter_by(customer_id=customer.id).all()
    assert observer.fired is True
    assert result.retry_count == 1
    assert len(versions) == 1
    assert versions[0].input_seq == customer.profile_input_seq
    assert versions[0].profile_json["preferences"]["expressed"][0]["value"] == "Natural black"


def test_same_snapshot_concurrent_winner_is_reused_instead_of_duplicate_version(db):
    customer = _customer(db, "same-snapshot-winner")
    winner = {}

    def publish_winner():
        winner["result"] = compile_customer_profile(db, customer.id)

    result = compile_customer_profile(
        db,
        customer.id,
        observer=_OneShotObserver("before_publish_cas", publish_winner),
    )

    assert winner["result"].created is True
    assert result.created is False
    assert result.profile_version_id == winner["result"].profile_version_id
    assert db.query(CustomerProfileVersion).filter_by(customer_id=customer.id).count() == 1


def test_trigger_event_must_belong_to_compiled_customer(db):
    customer = _customer(db, "event-owner")
    other = _customer(db, "event-other")
    source = append_source_record(
        db,
        customer_id=other.id,
        source_system="alibaba",
        source_account_key="profile-trigger-test",
        source_entity_type="inquiry",
        external_record_id="cross-customer-trigger",
        payload_schema_version="alibaba_inquiry_v1",
        payload_json={"subject": "Cross customer"},
        occurred_at=beijing_now(),
    )
    event = append_customer_event(
        db,
        customer_id=other.id,
        event_type="inquiry.received",
        event_source="alibaba",
        source_ref_type="source_record",
        source_ref_id=str(source.id),
        event_title="Inquiry received",
        event_payload={"channel": "alibaba"},
        payload_schema_version="customer_event_v1",
        occurred_at=source.occurred_at,
    )

    with pytest.raises(ProfileCompileError) as blocked:
        compile_customer_profile(db, customer.id, trigger_event_id=event.id)

    assert getattr(blocked.value, "error_code", None) == "TRIGGER_EVENT_CUSTOMER_MISMATCH"


def test_confirmed_fact_wins_within_same_semantic_key(db):
    customer = _customer(db, "confirmed")
    _fact(
        db,
        customer,
        key="business.industry",
        value="General trading",
        layer="source",
        observed_at=beijing_now(),
        fingerprint_suffix="source",
    )
    confirmed = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair extensions",
        layer="confirmed",
        observed_at=beijing_now() - timedelta(days=30),
        fingerprint_suffix="confirmed",
    )

    result = compile_customer_profile(db, customer.id)
    industry = db.get(CustomerProfileVersion, result.profile_version_id).profile_json[
        "business"
    ]["industry"]

    assert industry["value"] == "Hair extensions"
    assert industry["fact_layer"] == "confirmed"
    assert industry["fact_id"] == confirmed.id


def test_disputed_confirmed_fact_does_not_override_verified_current_fact(db):
    customer = _customer(db, "disputed-confirmed")
    verified = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair extensions",
        layer="source",
        status="verified",
        fingerprint_suffix="verified",
    )
    _fact(
        db,
        customer,
        key="business.industry",
        value="Unresolved conflicting industry",
        layer="confirmed",
        status="disputed",
        fingerprint_suffix="disputed",
    )

    result = compile_customer_profile(db, customer.id)
    industry = db.get(CustomerProfileVersion, result.profile_version_id).profile_json[
        "business"
    ]["industry"]

    assert industry["fact_id"] == verified.id
    assert industry["value"] == "Hair extensions"


def test_expressed_and_observed_preferences_remain_distinct_and_conflicted(db):
    customer = _customer(db, "preference-conflict")
    expressed = _fact(
        db,
        customer,
        key="preference.expressed.color",
        value="Blonde",
        layer="expressed",
        fingerprint_suffix="expressed",
    )
    observed = _fact(
        db,
        customer,
        key="preference.observed.color",
        value="Natural black",
        layer="observed",
        fingerprint_suffix="observed",
    )

    result = compile_customer_profile(db, customer.id)
    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json

    assert profile["preferences"]["expressed"][0]["value"] == "Blonde"
    assert profile["preferences"]["observed"][0]["value"] == "Natural black"
    assert profile["preferences"]["conflicts"] == [{
        "attribute": "color",
        "expressed_fact_ids": [expressed.id],
        "observed_fact_ids": [observed.id],
        "status": "open",
    }]


def test_quality_classification_includes_restricted_conflict_metadata(db):
    customer = _customer(db, "conflict-classification")
    left = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair",
        layer="source",
        fingerprint_suffix="left",
    )
    right = _fact(
        db,
        customer,
        key="business.industry",
        value="Beauty",
        layer="source",
        fingerprint_suffix="right",
    )
    db.add(CustomerFactConflict(
        customer_id=customer.id,
        conflict_key="business.industry",
        left_fact_id=min(left.id, right.id),
        right_fact_id=max(left.id, right.id),
        conflict_type="contradictory",
        data_classification="restricted_internal",
        visibility_scope="management",
        detection_rule_version="test_v1",
        conflict_fingerprint=_digest("restricted-conflict"),
        status="open",
        detected_at=beijing_now(),
    ))
    customer.profile_input_seq += 1
    db.flush()

    result = compile_customer_profile(db, customer.id)
    quality = db.get(CustomerProfileVersion, result.profile_version_id).profile_json[
        "quality"
    ]
    version = db.get(CustomerProfileVersion, result.profile_version_id)

    assert quality["max_data_classification"] == "restricted_internal"
    assert quality["max_visibility_scope"] == "management"
    assert version.evidence_fact_ids == sorted([left.id, right.id])


def test_expired_fact_is_not_current_and_is_reported_stale(db):
    customer = _customer(db, "stale")
    stale = _fact(
        db,
        customer,
        key="behavior.inferred.churn_risk",
        value="high",
        layer="inferred",
        expires_at=beijing_now() - timedelta(seconds=1),
    )

    result = compile_customer_profile(db, customer.id)
    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    context = db.get(CustomerAgentContext, customer.id).context_json

    assert profile["behavior"]["inferred"] == []
    assert profile["quality"]["stale_facts"] == [{
        "fact_id": stale.id,
        "fact_key": stale.fact_key,
        "expires_at": stale.expires_at.isoformat(timespec="seconds"),
        "data_classification": "internal_business",
        "visibility_scope": "customer_team",
    }]
    assert context["data_quality"]["stale_facts"] == profile["quality"]["stale_facts"]


def test_context_excludes_restricted_or_management_facts_but_profile_keeps_them(db):
    customer = _customer(db, "classification")
    restricted = _fact(
        db,
        customer,
        key="behavior.confirmed.relationship_note",
        value="Private risk detail",
        layer="confirmed",
        classification="restricted_internal",
        visibility="management",
    )
    public = _fact(
        db,
        customer,
        key="behavior.confirmed.priority",
        value="A",
        layer="confirmed",
        classification="internal_business",
        visibility="customer_team",
        fingerprint_suffix="safe",
    )
    stale_restricted = _fact(
        db,
        customer,
        key="behavior.inferred.churn_risk",
        value="secret-stale-risk",
        layer="inferred",
        classification="restricted_internal",
        visibility="management",
        expires_at=beijing_now() - timedelta(seconds=1),
        fingerprint_suffix="stale-restricted",
    )

    result = compile_customer_profile(db, customer.id)
    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    context = db.get(CustomerAgentContext, customer.id)

    assert {item["fact_id"] for item in profile["behavior"]["confirmed"]} == {
        restricted.id,
        public.id,
    }
    assert {item["fact_id"] for item in context.context_json["behavior_patterns"]["confirmed"]} == {
        public.id,
    }
    assert context.max_data_classification == "internal_business"
    assert "Private risk detail" not in str(context.context_json)
    assert "secret-stale-risk" not in str(context.context_json)
    assert stale_restricted.id not in {
        item["fact_id"] for item in context.context_json["data_quality"]["stale_facts"]
    }
    assert restricted.id not in {
        item["fact_id"] for item in context.context_json["evidence_refs"]
    }
    behavior_change = next(
        item for item in context.context_json["recent_changes"]
        if item["section"] == "behavior"
    )
    assert behavior_change["evidence_fact_ids"] == [public.id]
    assert profile["quality"]["max_data_classification"] == "restricted_internal"


def test_list_and_target_match_do_not_materialize_restricted_fact_values(db):
    customer = _customer(db, "restricted-projections")
    restricted = _fact(
        db,
        customer,
        key="business.industry",
        value="Secret vertical",
        layer="confirmed",
        classification="restricted_internal",
        visibility="management",
    )
    target = AcquisitionProfile(
        profile_key="secret-vertical",
        company_name="LeShine",
        products=[],
        advantages=[],
        target_countries=[],
        target_industries=["Secret vertical"],
        target_roles=[],
        exclusions=[],
        status="active",
    )
    db.add(target)
    db.flush()

    compile_customer_profile(db, customer.id)

    projection = db.get(CustomerListProjection, customer.id)
    match = db.query(CustomerTargetMatch).filter_by(
        customer_id=customer.id,
        target_profile_id=target.id,
        is_current=True,
    ).one()
    assert projection.primary_industry is None
    assert match.evidence_fact_ids == []
    assert restricted.id not in match.evidence_fact_ids


def test_projection_failure_keeps_previous_projection_and_reports_staleness(db):
    customer = _customer(db, "projection-failure")
    first = compile_customer_profile(db, customer.id)
    old_context = db.get(CustomerAgentContext, customer.id)
    old_context_version_id = old_context.profile_version_id
    _fact(
        db,
        customer,
        key="business.industry",
        value="Hair care",
        layer="source",
    )

    def fail_context():
        raise RuntimeError("simulated sensitive backend detail")

    result = compile_customer_profile(
        db,
        customer.id,
        observer=_OneShotObserver("before_agent_context_projection", fail_context),
    )

    assert result.created is True
    assert result.profile_version_id != first.profile_version_id
    assert db.get(CustomerAgentContext, customer.id).profile_version_id == old_context_version_id
    status = result.projections["agent_context"]
    assert status.status == "stale"
    assert status.profile_version_id == old_context_version_id
    assert status.target_profile_version_id == result.profile_version_id
    assert status.error_code == "PROJECTION_BUILD_FAILED"
    assert "sensitive" not in repr(status)
    assert db.get(CustomerListProjection, customer.id).profile_version_id == result.profile_version_id


def test_no_change_retry_repairs_a_failed_projection_without_new_profile_version(db):
    customer = _customer(db, "projection-retry")

    failed = compile_customer_profile(
        db,
        customer.id,
        observer=_OneShotObserver(
            "before_agent_context_projection",
            lambda: (_ for _ in ()).throw(RuntimeError("simulated")),
        ),
    )
    assert failed.projections["agent_context"].status == "failed"
    assert db.get(CustomerAgentContext, customer.id) is None

    repaired = compile_customer_profile(db, customer.id)

    assert repaired.created is False
    assert repaired.profile_version_id == failed.profile_version_id
    assert db.query(CustomerProfileVersion).filter_by(customer_id=customer.id).count() == 1
    assert repaired.projections["agent_context"].status == "current"
    assert db.get(CustomerAgentContext, customer.id).profile_version_id == failed.profile_version_id


def test_target_match_is_built_for_each_active_profile_from_published_version(db):
    customer = _customer(db, "target")
    fact = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair extensions",
        layer="source",
    )
    active = AcquisitionProfile(
        profile_key="hair-us",
        company_name="LeShine",
        products=["Wigs"],
        advantages=[],
        target_countries=["US"],
        target_industries=["Hair extensions"],
        target_roles=[],
        exclusions=[],
        status="active",
    )
    inactive = AcquisitionProfile(
        profile_key="inactive",
        company_name="LeShine",
        products=[],
        advantages=[],
        target_countries=[],
        target_industries=[],
        target_roles=[],
        exclusions=[],
        status="inactive",
    )
    db.add_all([active, inactive])
    db.flush()

    result = compile_customer_profile(db, customer.id)

    matches = db.query(CustomerTargetMatch).filter_by(customer_id=customer.id).all()
    assert len(matches) == 1
    assert matches[0].target_profile_id == active.id
    assert matches[0].is_current is True
    assert matches[0].score_reasons["schema_version"] == "target_match_v1"
    assert matches[0].score_reasons["profile_version_id"] == result.profile_version_id
    assert matches[0].evidence_fact_ids == [fact.id]


def test_target_match_product_evidence_excludes_unrelated_restricted_preferences(db):
    customer = _customer(db, "target-product-security")
    product = _fact(
        db,
        customer,
        key="preference.expressed.product_family",
        value="Wigs",
        layer="expressed",
        classification="internal_business",
        visibility="customer_team",
        fingerprint_suffix="product",
    )
    restricted = _fact(
        db,
        customer,
        key="preference.expressed.color",
        value="Confidential custom shade",
        layer="expressed",
        classification="restricted_internal",
        visibility="management",
        fingerprint_suffix="restricted-color",
    )
    target = AcquisitionProfile(
        profile_key="wigs-secure",
        company_name="LeShine",
        products=["Wigs"],
        advantages=[],
        target_countries=[],
        target_industries=[],
        target_roles=[],
        exclusions=[],
        status="active",
    )
    db.add(target)
    db.flush()

    compile_customer_profile(db, customer.id)

    match = db.query(CustomerTargetMatch).filter_by(
        customer_id=customer.id,
        target_profile_id=target.id,
        is_current=True,
    ).one()
    assert match.evidence_fact_ids == [product.id]
    assert restricted.id not in match.evidence_fact_ids


def test_candidate_fact_can_score_but_cannot_auto_qualify_target_match(db):
    customer = _customer(db, "target-candidate-ceiling")
    _fact(
        db,
        customer,
        key="business.industry",
        value="Hair extensions",
        layer="source",
        status="candidate",
    )
    target = AcquisitionProfile(
        profile_key="candidate-ceiling",
        company_name="LeShine",
        products=[],
        advantages=[],
        target_countries=[],
        target_industries=["Hair extensions"],
        target_roles=[],
        exclusions=[],
        status="active",
    )
    db.add(target)
    db.flush()

    compile_customer_profile(db, customer.id)

    match = db.query(CustomerTargetMatch).filter_by(
        customer_id=customer.id,
        target_profile_id=target.id,
        is_current=True,
    ).one()
    assert match.match_score == Decimal("100.00")
    assert match.match_status == "candidate"
