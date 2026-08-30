"""Versioned customer profile compiler contracts."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

import app.customer.profile_service as profile_service
from app.core.database import Base
from app.core.time import beijing_now
from app.customer.fact_service import append_customer_event, append_source_record
from app.customer.models import (
    CustomerAccount,
    CustomerAgentContext,
    CustomerAnnotation,
    CustomerAssignment,
    CustomerExternalIdentity,
    CustomerFact,
    CustomerFactConflict,
    CustomerListProjection,
    CustomerName,
    CustomerProfileVersion,
    CustomerRelationship,
    CustomerTargetMatch,
)
from app.customer.profile_service import (
    ProfileCompileError,
    compile_customer_profile as _compile_customer_profile,
)
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


def _session_factory(db):
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def compile_customer_profile(db, customer_id: int, **kwargs):
    """Commit test fixtures, then exercise the compiler's owned transactions."""
    db.commit()
    result = _compile_customer_profile(_session_factory(db), customer_id, **kwargs)
    db.expire_all()
    return result


def test_public_compile_api_owns_fresh_sessions_and_transactions(db):
    customer = _customer(db, "factory-api")
    customer_id = customer.id
    db.commit()
    caller_pending = AcquisitionProfile(
        profile_key="caller-pending",
        company_name="Pending",
        products=[],
        advantages=[],
        target_countries=[],
        target_industries=[],
        target_roles=[],
        exclusions=[],
        status="inactive",
    )
    db.add(caller_pending)

    result = _compile_customer_profile(_session_factory(db), customer_id)

    assert result.created is True
    assert caller_pending in db.new
    db.expire_all()
    assert db.get(CustomerAccount, customer_id).current_profile_version_id == (
        result.profile_version_id
    )


def test_cas_retry_closes_old_attempt_and_new_snapshot_sees_committed_fact(db):
    customer = _customer(db, "fresh-cas-attempt")
    customer_id = customer.id
    db.commit()
    factory = _session_factory(db)
    seen_sessions: list[tuple[str, object]] = []
    writer_session = None

    def observe(phase, compile_db, _customer_id, _base_seq):
        nonlocal writer_session
        seen_sessions.append((phase, compile_db))
        if phase != "before_publish_cas" or writer_session is not None:
            return
        with factory() as writer:
            writer_session = writer
            with writer.begin():
                writer_customer = writer.get(CustomerAccount, customer_id)
                _fact(
                    writer,
                    writer_customer,
                    key="business.industry",
                    value="Newly committed wigs",
                    layer="source",
                    fingerprint_suffix="fresh-transaction",
                )

    result = _compile_customer_profile(factory, customer_id, observer=observe)

    snapshot_sessions = [session for phase, session in seen_sessions if phase == "after_snapshot"]
    publish_sessions = [
        session for phase, session in seen_sessions
        if phase in {"before_publish_cas", "before_no_change_cas"}
    ]
    assert result.retry_count == 1
    assert len(snapshot_sessions) == 2
    assert len({id(session) for session in snapshot_sessions + publish_sessions}) == 4
    assert writer_session not in snapshot_sessions + publish_sessions
    assert all(not session.in_transaction() for session in snapshot_sessions + publish_sessions)
    with factory() as check:
        version = check.get(CustomerProfileVersion, result.profile_version_id)
        account = check.get(CustomerAccount, customer_id)
        assert version.input_seq == account.profile_input_seq
        assert version.profile_json["business"]["industry"]["value"] == (
            "Newly committed wigs"
        )
        assert check.query(CustomerProfileVersion).filter_by(
            customer_id=customer_id
        ).count() == 1


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


def test_private_annotation_and_unknown_visibility_fail_closed_in_projections(db):
    customer = _customer(db, "private-fail-closed")
    unknown = _fact(
        db,
        customer,
        key="business.industry",
        value="Undisclosed private vertical",
        layer="source",
        classification="unexpected_classification",
        visibility="unexpected_scope",
    )
    db.add(CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="do_not_contact",
        target_fact_id=None,
        content_schema_version="v1",
        content_json={"reason": "private reason must stay in the source row"},
        policy_scope_type="unexpected_private_scope",
        policy_scope_ref_id="secret-private-scope-ref",
        policy_effective_at=beijing_now(),
        visibility="private",
        data_classification="internal_business",
        status="active",
        authored_by=987654,
    ))
    target = AcquisitionProfile(
        profile_key="private-fail-closed",
        company_name="LeShine",
        products=[],
        advantages=[],
        target_countries=[],
        target_industries=["Undisclosed private vertical"],
        target_roles=[],
        exclusions=[],
        status="active",
    )
    db.add(target)
    customer.profile_input_seq += 2
    db.flush()

    result = compile_customer_profile(db, customer.id)

    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    context = db.get(CustomerAgentContext, customer.id).context_json
    projection = db.get(CustomerListProjection, customer.id)
    match = db.query(CustomerTargetMatch).filter_by(
        customer_id=customer.id,
        target_profile_id=target.id,
        is_current=True,
    ).one()
    assert profile["quality"]["max_visibility_scope"] == "private"
    assert profile["quality"]["max_data_classification"] == "restricted_internal"
    assert profile["risks"]["has_active_dnc"] is True
    assert "private reason" not in str(profile)
    assert "secret-private-scope-ref" not in str(profile)
    dnc_risk = next(
        item for item in profile["risks"]["items"]
        if item["risk_type"] == "do_not_contact"
    )
    assert dnc_risk["scope_type"] == "global"
    assert dnc_risk["security_transform"] == "dnc_enforcement_v1"
    assert "scope_ref_id" not in dnc_risk
    assert context["business_profile"]["industry"] is None
    assert unknown.id not in {item["fact_id"] for item in context["evidence_refs"]}
    assert all(item["section"] != "business" for item in context["recent_changes"])
    assert all(item["section"] != "quality" for item in context["recent_changes"])
    assert projection.primary_industry is None
    assert context["risks"]["has_active_dnc"] is True
    assert "secret-private-scope-ref" not in str(context)
    assert projection.has_active_dnc is True
    assert projection.global_claim_blocked is True
    assert projection.global_claim_block_reason == "do_not_contact"
    assert match.evidence_fact_ids == []


def test_active_correction_blocks_target_and_later_agent_fact_for_same_key(db):
    customer = _customer(db, "active-correction")
    target = _fact(
        db,
        customer,
        key="business.industry",
        value="Incorrect industry",
        layer="inferred",
        fingerprint_suffix="corrected-target",
    )
    target.agent_run_id = 71001
    db.add(CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="correction",
        target_fact_id=target.id,
        content_schema_version="v1",
        content_json={"reason": "Salesperson rejected this conclusion"},
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=987654,
    ))
    later_agent = _fact(
        db,
        customer,
        key="business.industry",
        value="Later silent agent replacement",
        layer="inferred",
        observed_at=beijing_now() + timedelta(seconds=1),
        fingerprint_suffix="later-agent",
    )
    later_agent.agent_run_id = 71002
    customer.profile_input_seq += 1
    db.flush()

    result = compile_customer_profile(db, customer.id)

    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    context = db.get(CustomerAgentContext, customer.id).context_json
    assert profile["business"]["industry"] is None
    assert profile["quality"]["corrections"] == [{
        "target_fact_id": target.id,
        "fact_key": "business.industry",
        "status": "active",
        "data_classification": "internal_business",
        "visibility_scope": "customer_team",
        "open_question": "review_correction:business.industry",
    }]
    assert "review_correction:business.industry" in profile["quality"]["open_questions"]
    assert context["data_quality"]["corrections"] == profile["quality"]["corrections"]
    assert target.id not in {item["fact_id"] for item in context["evidence_refs"]}
    assert later_agent.id not in {item["fact_id"] for item in context["evidence_refs"]}


def test_correction_rejects_cross_customer_target_fact(db):
    customer = _customer(db, "correction-owner")
    other = _customer(db, "correction-other")
    other_fact = _fact(
        db,
        other,
        key="business.industry",
        value="Other customer industry",
        layer="source",
    )
    db.add(CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="correction",
        target_fact_id=other_fact.id,
        content_schema_version="v1",
        content_json={"reason": "invalid cross-customer reference"},
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=987654,
    ))
    customer.profile_input_seq += 1
    db.flush()

    with pytest.raises(ProfileCompileError) as blocked:
        compile_customer_profile(db, customer.id)

    assert blocked.value.error_code == "CORRECTION_ANNOTATION_INVALID"


def test_revoked_and_private_corrections_do_not_change_shared_profile(db):
    customer = _customer(db, "correction-not-shared")
    fact = _fact(
        db,
        customer,
        key="business.industry",
        value="Current verified industry",
        layer="source",
    )
    for suffix, status, visibility in (
        ("revoked", "revoked", "customer_team"),
        ("private", "active", "private"),
    ):
        db.add(CustomerAnnotation(
            customer_id=customer.id,
            annotation_type="correction",
            target_fact_id=fact.id,
            content_schema_version="v1",
            content_json={"reason": suffix},
            visibility=visibility,
            data_classification="internal_business",
            status=status,
            authored_by=987654,
        ))
    customer.profile_input_seq += 2
    db.flush()

    result = compile_customer_profile(db, customer.id)

    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    assert profile["business"]["industry"]["fact_id"] == fact.id
    assert profile["quality"]["corrections"] == []


def test_active_shared_correction_rejects_unknown_visibility(db):
    customer = _customer(db, "correction-unknown-visibility")
    fact = _fact(
        db,
        customer,
        key="business.industry",
        value="Industry",
        layer="source",
    )
    db.add(CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="correction",
        target_fact_id=fact.id,
        content_schema_version="v1",
        content_json={"reason": "invalid visibility"},
        visibility="unexpected_scope",
        data_classification="internal_business",
        status="active",
        authored_by=987654,
    ))
    customer.profile_input_seq += 1
    db.flush()

    with pytest.raises(ProfileCompileError) as blocked:
        compile_customer_profile(db, customer.id)

    assert blocked.value.error_code == "CORRECTION_ANNOTATION_INVALID"


def test_jcs_semantic_sets_ignore_duplicate_alias_identity_relationship_and_evidence(db):
    customer = _customer(db, "semantic-set")
    related = _customer(db, "semantic-set-related")
    now = beijing_now().replace(microsecond=0)

    def add_alias(suffix: str):
        db.add(CustomerName(
            customer_id=customer.id,
            name="Semantic Trading",
            normalized_name="semantic trading",
            name_type="trading",
            verification_status="verified",
            confidence=Decimal("0.9000"),
            confidence_method_version="confidence_v1",
            confidence_components_json={"source_authority": 0.9},
            name_fingerprint=_digest(f"semantic-alias-{suffix}"),
            first_seen_at=now,
            last_seen_at=now,
        ))

    def add_identity(suffix: str):
        db.add(CustomerExternalIdentity(
            customer_id=customer.id,
            contact_id=None,
            source_system="linkedin",
            source_account_key="global",
            identifier_type="company_page_url",
            raw_value="https://linkedin.example/company/semantic",
            normalized_value="linkedin.example/company/semantic",
            identity_strength="strong",
            cardinality="one_to_one",
            auto_match_ceiling="verified",
            verification_status="verified",
            confidence=Decimal("0.9000"),
            confidence_method_version="confidence_v1",
            confidence_components_json={"source_authority": 0.9},
            is_primary=False,
            first_seen_at=now,
            last_seen_at=now,
            verified_at=now,
            status="active",
            identity_fingerprint=_digest(f"semantic-identity-{suffix}"),
        ))

    def add_relationship(suffix: str):
        db.add(CustomerRelationship(
            from_customer_id=customer.id,
            to_customer_id=related.id,
            relationship_type="affiliate",
            verification_status="verified",
            confidence=Decimal("0.9000"),
            confidence_method_version="confidence_v1",
            confidence_components_json={"source_authority": 0.9},
            source_fact_id=None,
            effective_from=now,
            effective_to=None,
            relationship_fingerprint=_digest(f"semantic-relationship-{suffix}"),
        ))

    add_alias("one")
    add_identity("one")
    add_relationship("one")
    industry = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair",
        layer="source",
    )
    industry.value_json = {
        "value": "Hair",
        "supporting_fact_ids": [industry.id],
    }
    customer.profile_input_seq += 3
    db.flush()
    first = compile_customer_profile(db, customer.id)

    add_alias("two")
    add_identity("two")
    add_relationship("two")
    industry = db.get(CustomerFact, industry.id)
    industry.value_json = {
        "value": "Hair",
        "supporting_fact_ids": [industry.id, industry.id],
    }
    customer = db.get(CustomerAccount, customer.id)
    customer.profile_input_seq += 4
    db.flush()

    replay = compile_customer_profile(db, customer.id)

    assert replay.created is False
    assert replay.profile_version_id == first.profile_version_id
    assert db.query(CustomerProfileVersion).filter_by(customer_id=customer.id).count() == 1


def test_registered_risks_and_evidence_descriptions_are_safe_and_layered(db):
    customer = _customer(db, "registered-risks")
    churn = _fact(
        db,
        customer,
        key="behavior.inferred.churn_risk",
        value="high secret score",
        layer="inferred",
        fingerprint_suffix="churn",
    )
    silence = _fact(
        db,
        customer,
        key="behavior.observed.silence_period",
        value=45,
        layer="observed",
        fingerprint_suffix="silence",
    )
    supplier = _fact(
        db,
        customer,
        key="behavior.inferred.supplier_switch_signal",
        value="management-only supplier detail",
        layer="inferred",
        visibility="management",
        fingerprint_suffix="supplier",
    )
    db.add(CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="do_not_contact",
        target_fact_id=None,
        content_schema_version="v1",
        content_json={"reason": "must not appear in risk summary"},
        policy_scope_type="global",
        policy_scope_ref_id=None,
        policy_effective_at=beijing_now(),
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=987654,
    ))
    customer.profile_input_seq += 1
    db.flush()

    result = compile_customer_profile(db, customer.id)

    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    context = db.get(CustomerAgentContext, customer.id).context_json
    assert {item["risk_type"] for item in profile["risks"]["items"]} == {
        "churn_risk",
        "silence_period",
        "supplier_switch_signal",
        "do_not_contact",
    }
    profile_risks = {item["risk_type"]: item for item in profile["risks"]["items"]}
    assert profile_risks["churn_risk"]["fact_id"] == churn.id
    assert profile_risks["churn_risk"]["fact_layer"] == "inferred"
    assert profile_risks["do_not_contact"]["risk_source"] == "annotation"
    assert {item["risk_type"] for item in context["risks"]["items"]} == {
        "churn_risk",
        "silence_period",
        "do_not_contact",
    }
    evidence = {item["fact_id"]: item for item in context["evidence_refs"]}
    assert churn.id in evidence
    assert silence.id in evidence
    assert supplier.id not in evidence
    assert all(item["description"].strip() for item in evidence.values())
    assert all("high secret score" not in item["description"] for item in evidence.values())
    assert all("45" not in item["description"] for item in evidence.values())


def test_compile_retries_when_fact_expires_between_snapshot_and_publish(db, monkeypatch):
    before_expiry = datetime(2026, 1, 1, 9, 0, 0)
    after_expiry = before_expiry + timedelta(seconds=2)
    customer = _customer(db, "expiry-boundary")
    fact = _fact(
        db,
        customer,
        key="behavior.inferred.churn_risk",
        value="high",
        layer="inferred",
        observed_at=before_expiry - timedelta(days=1),
        expires_at=before_expiry + timedelta(seconds=1),
    )
    clock = {"now": before_expiry}
    monkeypatch.setattr(profile_service, "beijing_now", lambda: clock["now"])

    result = compile_customer_profile(
        db,
        customer.id,
        observer=_OneShotObserver(
            "before_publish_cas",
            lambda: clock.update(now=after_expiry),
        ),
    )

    version = db.get(CustomerProfileVersion, result.profile_version_id)
    assert result.retry_count == 1
    assert version.compiled_at == after_expiry
    assert version.profile_json["behavior"]["inferred"] == []
    assert version.profile_json["quality"]["stale_facts"][0]["fact_id"] == fact.id


def test_compile_retries_across_business_validity_boundaries(db, monkeypatch):
    before_boundary = datetime(2026, 1, 1, 10, 0, 0)
    boundary = before_boundary + timedelta(seconds=1)
    after_boundary = boundary + timedelta(seconds=1)
    customer = _customer(db, "business-validity-boundary")
    related = _customer(db, "business-validity-related")
    ending_fact = _fact(
        db,
        customer,
        key="behavior.observed.preferred_channel",
        value="email",
        layer="observed",
        observed_at=before_boundary - timedelta(days=2),
        fingerprint_suffix="ending",
    )
    ending_fact.effective_from = before_boundary - timedelta(days=1)
    ending_fact.effective_to = boundary
    starting_fact = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair products",
        layer="source",
        observed_at=before_boundary - timedelta(days=2),
        fingerprint_suffix="starting",
    )
    starting_fact.effective_from = boundary
    db.add_all([
        CustomerName(
            customer_id=customer.id,
            name="Ending Alias",
            normalized_name="ending alias",
            name_type="trading",
            verification_status="verified",
            confidence=Decimal("0.9000"),
            confidence_method_version="confidence_v1",
            confidence_components_json={"source_authority": 0.9},
            name_fingerprint=_digest("ending-validity-alias"),
            first_seen_at=before_boundary - timedelta(days=2),
            last_seen_at=before_boundary - timedelta(days=1),
            valid_from=before_boundary - timedelta(days=1),
            valid_to=boundary,
        ),
        CustomerName(
            customer_id=customer.id,
            name="Starting Alias",
            normalized_name="starting alias",
            name_type="trading",
            verification_status="verified",
            confidence=Decimal("0.9000"),
            confidence_method_version="confidence_v1",
            confidence_components_json={"source_authority": 0.9},
            name_fingerprint=_digest("starting-validity-alias"),
            first_seen_at=before_boundary - timedelta(days=1),
            last_seen_at=before_boundary - timedelta(days=1),
            valid_from=boundary,
            valid_to=None,
        ),
        CustomerRelationship(
            from_customer_id=customer.id,
            to_customer_id=related.id,
            relationship_type="affiliate",
            verification_status="verified",
            confidence=Decimal("0.9000"),
            confidence_method_version="confidence_v1",
            confidence_components_json={"source_authority": 0.9},
            effective_from=before_boundary - timedelta(days=1),
            effective_to=boundary,
            relationship_fingerprint=_digest("ending-validity-relationship"),
        ),
        CustomerAssignment(
            customer_id=customer.id,
            user_id=987654,
            assignment_role="primary",
            assignment_status="active",
            assignment_source="manual",
            effective_from=before_boundary - timedelta(days=1),
            effective_to=boundary,
        ),
    ])
    customer.profile_input_seq += 4
    db.flush()
    clock = {"now": before_boundary}
    monkeypatch.setattr(profile_service, "beijing_now", lambda: clock["now"])

    result = compile_customer_profile(
        db,
        customer.id,
        observer=_OneShotObserver(
            "before_publish_cas",
            lambda: clock.update(now=after_boundary),
        ),
    )

    version = db.get(CustomerProfileVersion, result.profile_version_id)
    profile = version.profile_json
    assert result.retry_count == 1
    assert profile["business"]["industry"]["fact_id"] == starting_fact.id
    assert profile["behavior"]["observed"] == []
    assert ending_fact.id not in version.evidence_fact_ids
    assert [item["name"] for item in profile["identity"]["aliases"]] == [
        "Starting Alias"
    ]
    assert profile["business"]["related_companies"] == []
    assert profile["ownership"]["is_public_pool"] is True
    assert version.data_as_of == boundary


def test_older_evaluation_retries_after_same_seq_newer_compile(db, monkeypatch):
    older = datetime(2026, 1, 2, 9, 0, 0)
    newer = older + timedelta(minutes=1)
    customer = _customer(db, "newer-compile-wins")
    customer_id = customer.id
    db.commit()
    factory = _session_factory(db)
    clock = {"now": older}
    monkeypatch.setattr(profile_service, "beijing_now", lambda: clock["now"])
    winner = {}

    def publish_newer():
        clock["now"] = newer
        winner["result"] = _compile_customer_profile(factory, customer_id)

    result = _compile_customer_profile(
        factory,
        customer_id,
        observer=_OneShotObserver("before_publish_cas", publish_newer),
    )

    assert winner["result"].created is True
    assert result.created is False
    assert result.retry_count == 1
    assert result.profile_version_id == winner["result"].profile_version_id


def test_future_private_dnc_becomes_enforced_when_compile_crosses_boundary(db, monkeypatch):
    before_policy = datetime(2026, 1, 3, 9, 0, 0)
    after_policy = before_policy + timedelta(seconds=2)
    customer = _customer(db, "future-private-dnc")
    db.add(CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="do_not_contact",
        target_fact_id=None,
        content_schema_version="v1",
        content_json={"reason": "private future reason"},
        policy_scope_type="global",
        policy_scope_ref_id=None,
        policy_effective_at=before_policy + timedelta(seconds=1),
        visibility="private",
        data_classification="restricted_internal",
        status="active",
        authored_by=987654,
    ))
    customer.profile_input_seq += 1
    db.flush()
    clock = {"now": before_policy}
    monkeypatch.setattr(profile_service, "beijing_now", lambda: clock["now"])

    result = compile_customer_profile(
        db,
        customer.id,
        observer=_OneShotObserver(
            "before_publish_cas",
            lambda: clock.update(now=after_policy),
        ),
    )

    profile = db.get(CustomerProfileVersion, result.profile_version_id).profile_json
    projection = db.get(CustomerListProjection, customer.id)
    assert result.retry_count == 1
    assert profile["risks"]["has_active_dnc"] is True
    assert projection.global_claim_blocked is True
    assert "private future reason" not in str(profile)


def test_restricted_inputs_do_not_change_public_quality_or_engagement_aggregates(db):
    baseline = _customer(db, "safe-aggregate-baseline")
    restricted = _customer(db, "safe-aggregate-restricted")
    _fact(
        db,
        restricted,
        key="business.industry",
        value="Restricted vertical",
        layer="source",
        classification="restricted_internal",
        visibility="management",
        fingerprint_suffix="restricted-industry",
    )
    _fact(
        db,
        restricted,
        key="preference.expressed.product_family",
        value="Restricted need",
        layer="expressed",
        classification="restricted_internal",
        visibility="private",
        fingerprint_suffix="restricted-need",
    )
    _fact(
        db,
        restricted,
        key="behavior.observed.preferred_channel",
        value="Restricted channel",
        layer="observed",
        classification="restricted_internal",
        visibility="management",
        fingerprint_suffix="restricted-behavior",
    )

    baseline_result = compile_customer_profile(db, baseline.id)
    restricted_result = compile_customer_profile(db, restricted.id)

    baseline_profile = db.get(
        CustomerProfileVersion,
        baseline_result.profile_version_id,
    ).profile_json
    restricted_profile = db.get(
        CustomerProfileVersion,
        restricted_result.profile_version_id,
    ).profile_json
    baseline_list = db.get(CustomerListProjection, baseline.id)
    restricted_list = db.get(CustomerListProjection, restricted.id)
    assert restricted_profile["quality"]["completeness"] == (
        baseline_profile["quality"]["completeness"]
    )
    assert restricted_list.data_quality_score == baseline_list.data_quality_score
    assert restricted_list.engagement_health == baseline_list.engagement_health


def test_target_match_projection_select_count_is_constant_with_target_count(db):
    def add_target(index: int):
        db.add(AcquisitionProfile(
            profile_key=f"query-count-{index}",
            company_name="LeShine",
            products=[],
            advantages=[],
            target_countries=[],
            target_industries=[],
            target_roles=[],
            exclusions=[],
            status="active",
        ))

    add_target(0)
    one_target_customer = _customer(db, "query-count-one")
    db.flush()
    select_counts = []

    def count_target_match_selects(_conn, _cursor, statement, _params, _context, _many):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "ark_customer_target_matches" in statement
        ):
            select_counts[-1] += 1

    event.listen(db.get_bind(), "before_cursor_execute", count_target_match_selects)
    try:
        select_counts.append(0)
        compile_customer_profile(db, one_target_customer.id)
        for index in range(1, 9):
            add_target(index)
        many_target_customer = _customer(db, "query-count-many")
        db.flush()
        select_counts.append(0)
        compile_customer_profile(db, many_target_customer.id)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count_target_match_selects)

    assert select_counts[1] <= select_counts[0] + 1


def test_assignment_end_returns_to_pool_with_new_version_and_business_tombstone(db):
    customer = _customer(db, "assignment-round-trip")
    first = compile_customer_profile(db, customer.id)
    assigned_at = datetime(2024, 1, 1, 9, 0, 0)
    ended_at = datetime(2025, 1, 1, 9, 0, 0)
    assignment = CustomerAssignment(
        customer_id=customer.id,
        user_id=987654,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=assigned_at,
    )
    db.add(assignment)
    customer.profile_input_seq += 1
    db.flush()
    second = compile_customer_profile(db, customer.id)
    assignment = db.get(CustomerAssignment, assignment.id)
    customer = db.get(CustomerAccount, customer.id)
    assignment.assignment_status = "ended"
    assignment.effective_to = ended_at
    customer.profile_input_seq += 1
    db.flush()

    third = compile_customer_profile(db, customer.id)

    version = db.get(CustomerProfileVersion, third.profile_version_id)
    assert first.version_no == 1
    assert second.version_no == 2
    assert third.created is True
    assert third.version_no == 3
    assert version.profile_json["ownership"]["is_public_pool"] is True
    assert version.section_data_as_of["ownership"] == ended_at.isoformat()
    assert any(
        change["section"] == "ownership"
        for change in version.change_summary["changes"]
    )


@pytest.mark.parametrize("terminal_status", ["rejected", "superseded"])
def test_fact_terminal_status_returns_to_prior_state_with_business_tombstone(
    db,
    terminal_status,
):
    customer = _customer(db, f"fact-round-trip-{terminal_status}")
    first = compile_customer_profile(db, customer.id)
    observed_at = datetime(2024, 2, 1, 9, 0, 0)
    reviewed_at = datetime(2025, 2, 1, 9, 0, 0)
    fact = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair products",
        layer="source",
        observed_at=observed_at,
        fingerprint_suffix=terminal_status,
    )
    second = compile_customer_profile(db, customer.id)
    fact = db.get(CustomerFact, fact.id)
    customer = db.get(CustomerAccount, customer.id)
    fact.verification_status = terminal_status
    fact.reviewed_at = reviewed_at
    customer.profile_input_seq += 1
    db.flush()

    third = compile_customer_profile(db, customer.id)

    version = db.get(CustomerProfileVersion, third.profile_version_id)
    assert first.version_no == 1
    assert second.version_no == 2
    assert third.created is True
    assert third.version_no == 3
    assert version.profile_json["business"]["industry"] is None
    assert version.section_data_as_of["business"] == reviewed_at.isoformat()
    assert version.data_as_of == reviewed_at


@pytest.mark.parametrize("terminal_status", ["rejected", "superseded"])
def test_fact_terminal_tombstone_is_stable_without_terminal_time(
    db,
    terminal_status,
):
    customer = _customer(db, f"fact-null-tombstone-{terminal_status}")
    first = compile_customer_profile(db, customer.id)
    fact = _fact(
        db,
        customer,
        key="business.industry",
        value="Terminal industry",
        layer="source",
        observed_at=datetime(2020, 3, 1, 9, 0, 0),
        fingerprint_suffix=terminal_status,
    )
    second = compile_customer_profile(db, customer.id)
    fact = db.get(CustomerFact, fact.id)
    customer = db.get(CustomerAccount, customer.id)
    fact.verification_status = terminal_status
    assert fact.reviewed_at is None
    assert fact.effective_to is None
    customer.profile_input_seq += 1
    db.flush()

    third = compile_customer_profile(db, customer.id)
    version = db.get(CustomerProfileVersion, third.profile_version_id)
    context = db.get(CustomerAgentContext, customer.id).context_json
    customer = db.get(CustomerAccount, customer.id)
    customer.profile_input_seq += 1
    db.flush()
    replay = compile_customer_profile(db, customer.id)

    expected = {
        "object_type": "customer_fact",
        "fact_key": "business.industry",
        "fact_fingerprint": fact.fact_fingerprint,
        "terminal_status": terminal_status,
        "data_classification": "internal_business",
        "visibility_scope": "customer_team",
    }
    assert first.version_no == 1
    assert second.version_no == 2
    assert third.created is True
    assert third.version_no == 3
    assert version.profile_json["business"]["industry"] is None
    assert version.profile_json["quality"]["terminal_tombstones"] == [expected]
    assert context["data_quality"]["terminal_tombstones"] == [expected]
    assert any(
        change["section"] == "quality"
        for change in version.change_summary["changes"]
    )
    assert version.section_data_as_of["business"] is None
    assert version.data_as_of is None
    assert replay.created is False
    assert replay.profile_version_id == third.profile_version_id


@pytest.mark.parametrize("terminal_status", ["resolved", "dismissed", "superseded"])
def test_conflict_terminal_tombstone_is_stable_and_filtered_without_resolved_time(
    db,
    terminal_status,
):
    observed_at = datetime(2020, 4, 1, 9, 0, 0)
    customer = _customer(db, f"conflict-null-tombstone-{terminal_status}")
    left = _fact(
        db,
        customer,
        key="business.industry",
        value="Hair",
        layer="source",
        observed_at=observed_at,
        fingerprint_suffix=f"{terminal_status}-left",
    )
    right = _fact(
        db,
        customer,
        key="business.industry",
        value="Beauty",
        layer="source",
        observed_at=observed_at,
        fingerprint_suffix=f"{terminal_status}-right",
    )
    first = compile_customer_profile(db, customer.id)
    conflict = CustomerFactConflict(
        customer_id=customer.id,
        conflict_key="business.industry",
        left_fact_id=min(left.id, right.id),
        right_fact_id=max(left.id, right.id),
        conflict_type="contradictory",
        data_classification="restricted_internal",
        visibility_scope="management",
        detection_rule_version="test_v1",
        conflict_fingerprint=_digest(f"null-conflict-{terminal_status}"),
        status="open",
        detected_at=datetime(2021, 4, 1, 9, 0, 0),
    )
    db.add(conflict)
    customer.profile_input_seq += 1
    db.flush()
    second = compile_customer_profile(db, customer.id)
    conflict = db.get(CustomerFactConflict, conflict.id)
    customer = db.get(CustomerAccount, customer.id)
    conflict.status = terminal_status
    conflict.resolved_at = None
    customer.profile_input_seq += 1
    db.flush()

    third = compile_customer_profile(db, customer.id)
    version = db.get(CustomerProfileVersion, third.profile_version_id)
    context = db.get(CustomerAgentContext, customer.id).context_json
    customer = db.get(CustomerAccount, customer.id)
    customer.profile_input_seq += 1
    db.flush()
    replay = compile_customer_profile(db, customer.id)

    assert first.version_no == 1
    assert second.version_no == 2
    assert third.created is True
    assert third.version_no == 3
    assert version.profile_json["quality"]["terminal_tombstones"] == [{
        "object_type": "customer_fact_conflict",
        "conflict_key": "business.industry",
        "conflict_fingerprint": conflict.conflict_fingerprint,
        "terminal_status": terminal_status,
        "data_classification": "restricted_internal",
        "visibility_scope": "management",
    }]
    assert context["data_quality"]["terminal_tombstones"] == []
    assert conflict.conflict_fingerprint not in str(context)
    assert all(
        change["section"] != "quality"
        for change in context["recent_changes"]
    )
    assert version.data_as_of == observed_at
    assert replay.created is False
    assert replay.profile_version_id == third.profile_version_id


def test_revoked_correction_uses_stable_tombstone_without_revoked_time(db):
    observed_at = datetime(2020, 5, 1, 9, 0, 0)
    customer = _customer(db, "correction-null-tombstone")
    fact = _fact(
        db,
        customer,
        key="business.industry",
        value="Current industry",
        layer="source",
        observed_at=observed_at,
    )
    first = compile_customer_profile(db, customer.id)
    correction = CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="correction",
        target_fact_id=fact.id,
        content_schema_version="v1",
        content_json={"reason": "Reject the source conclusion"},
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=987654,
    )
    db.add(correction)
    customer.profile_input_seq += 1
    db.flush()
    second = compile_customer_profile(db, customer.id)
    correction = db.get(CustomerAnnotation, correction.id)
    customer = db.get(CustomerAccount, customer.id)
    correction.status = "revoked"
    correction.revoked_at = None
    customer.profile_input_seq += 1
    db.flush()

    third = compile_customer_profile(db, customer.id)
    version = db.get(CustomerProfileVersion, third.profile_version_id)
    context = db.get(CustomerAgentContext, customer.id).context_json
    customer = db.get(CustomerAccount, customer.id)
    customer.profile_input_seq += 1
    db.flush()
    replay = compile_customer_profile(db, customer.id)

    tombstone = version.profile_json["quality"]["terminal_tombstones"][0]
    assert first.version_no == 1
    assert second.version_no == 2
    assert third.created is True
    assert third.version_no == 3
    assert version.profile_json["business"]["industry"]["fact_id"] == fact.id
    assert tombstone == {
        "object_type": "customer_annotation",
        "annotation_type": "correction",
        "target_fact_fingerprint": fact.fact_fingerprint,
        "annotation_fingerprint": tombstone["annotation_fingerprint"],
        "terminal_status": "revoked",
        "data_classification": "internal_business",
        "visibility_scope": "customer_team",
    }
    assert len(tombstone["annotation_fingerprint"]) == 64
    assert "target_fact_id" not in tombstone
    assert context["data_quality"]["terminal_tombstones"] == [tombstone]
    assert version.data_as_of == observed_at
    assert replay.created is False
    assert replay.profile_version_id == third.profile_version_id


def test_historical_backfill_data_as_of_uses_business_time_not_account_audit_time(db):
    historical = datetime(2020, 5, 1, 9, 30, 0)
    customer = _customer(db, "historical-data-as-of")
    _fact(
        db,
        customer,
        key="business.industry",
        value="Historical hair business",
        layer="source",
        observed_at=historical,
    )

    result = compile_customer_profile(db, customer.id)

    version = db.get(CustomerProfileVersion, result.profile_version_id)
    assert version.data_as_of == historical
    assert version.section_data_as_of["business"] == historical.isoformat()
    assert version.section_data_as_of["identity"] is None


@pytest.mark.skipif(
    not os.getenv("CUSTOMER_TEST_MYSQL_URL"),
    reason="set CUSTOMER_TEST_MYSQL_URL only for an explicitly disposable MySQL schema",
)
def test_real_mysql_profile_cas_retry_uses_fresh_transactions():
    engine = create_engine(os.environ["CUSTOMER_TEST_MYSQL_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    suffix = str(beijing_now().timestamp()).replace(".", "")
    with factory() as seed:
        with seed.begin():
            customer = _customer(seed, f"mysql-profile-{suffix}")
            customer_id = customer.id
    writer_fired = False

    def observe(phase, _compile_db, _customer_id, _base_seq):
        nonlocal writer_fired
        if phase != "before_publish_cas" or writer_fired:
            return
        writer_fired = True
        with factory() as writer:
            with writer.begin():
                writer_customer = writer.get(CustomerAccount, customer_id)
                _fact(
                    writer,
                    writer_customer,
                    key="business.industry",
                    value="MySQL fresh fact",
                    layer="source",
                    fingerprint_suffix=suffix,
                )

    result = _compile_customer_profile(factory, customer_id, observer=observe)

    assert writer_fired is True
    assert result.retry_count == 1
    with factory() as check:
        version = check.get(CustomerProfileVersion, result.profile_version_id)
        account = check.get(CustomerAccount, customer_id)
        assert version.input_seq == account.profile_input_seq
        assert version.profile_json["business"]["industry"]["value"] == (
            "MySQL fresh fact"
        )
