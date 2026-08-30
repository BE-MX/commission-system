"""Secure, bounded Ark-only customer consumer tools."""

from datetime import datetime, timedelta
import importlib.util
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_runtime import evaluation_service
from app.agent_runtime.models import AgentRun
from app.auth.models import ArkUser
from app.core.database import Base
try:
    from app.customer import agent_service
except ImportError:
    agent_service = None
from app.customer import agent_tool_contract
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAgentContext,
    CustomerAgentRunScope,
    CustomerAssignment,
    CustomerConversation,
    CustomerFact,
    CustomerMessage,
    CustomerObjectOwnership,
    CustomerOrder,
    CustomerOrderItem,
    CustomerProfileVersion,
    CustomerSourceRecord,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        ArkUser.__table__, AgentRun.__table__, CustomerAccount.__table__,
        CustomerAssignment.__table__, CustomerProfileVersion.__table__,
        CustomerAgentContext.__table__, CustomerSourceRecord.__table__,
        CustomerFact.__table__, CustomerConversation.__table__,
        CustomerMessage.__table__, CustomerOrder.__table__, CustomerOrderItem.__table__,
        CustomerAction.__table__, CustomerObjectOwnership.__table__,
        CustomerAgentRunScope.__table__,
    ])
    session = sessionmaker(bind=engine, autoflush=False)()
    session.add_all([
        ArkUser(id=7, username="owner", password_hash="x", real_name="Owner"),
        ArkUser(id=8, username="other", password_hash="x", real_name="Other"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def settings(monkeypatch):
    value = SimpleNamespace(
        AGENT_RUNTIME_RUN_TOKEN_SECRET="customer-agent-cursor-secret-at-least-32",
        JWT_SECRET_KEY="fallback-secret-at-least-32-characters",
    )
    monkeypatch.setattr(agent_tool_contract, "get_settings", lambda: value)
    return value


def test_customer_agent_service_exists():
    assert agent_service is not None


def test_agent_tool_contract_module_exists():
    assert importlib.util.find_spec("app.customer.agent_tool_contract") is not None


def test_contract_clips_nested_strings_without_mutating_input():
    source = {"section": {"text": "x" * 2_100}}
    clipped, truncated = agent_tool_contract.clip(source)
    assert truncated is True
    assert len(clipped["section"]["text"]) == 2_000
    assert len(source["section"]["text"]) == 2_100


def _customer(db, name: str, *, owner: int = 7):
    row = CustomerAccount(
        customer_code=f"CUS-{name}", display_name=name,
        canonical_company_name=None if "Person" in name else f"{name} Ltd",
        entity_type="unknown" if "Person" in name else "registered_company",
        identity_status="provisional" if "Person" in name else "verified",
        relationship_stage="discovered", relationship_stage_changed_at=datetime(2026, 8, 1),
        relationship_stage_reason="test", record_status="active", identity_confidence=0.8,
        profile_completeness=50, profile_input_seq=1,
    )
    db.add(row)
    db.flush()
    version = CustomerProfileVersion(
        customer_id=row.id, version_no=1, profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1", input_seq=1,
        profile_json={"identity": {"display_name": name}, "secret": "never-return"},
        section_hashes={}, section_data_as_of={"identity": "2026-08-01T00:00:00"},
        evidence_fact_ids=[], change_summary={"changes": []},
        compiler_version="test", profile_fingerprint=f"{row.id:064x}",
        data_as_of=datetime(2026, 8, 1), compiled_at=datetime(2026, 8, 2),
    )
    db.add(version)
    db.flush()
    row.current_profile_version_id = version.id
    db.add(CustomerAssignment(
        customer_id=row.id, user_id=owner, assignment_role="primary",
        assignment_status="active", assignment_source="manual",
        effective_from=datetime(2026, 8, 1), operated_by=owner,
    ))
    db.add(CustomerAgentContext(
        customer_id=row.id, profile_version_id=version.id,
        context_schema_version="customer_context_v1",
        context_json={
            "identity": {"display_name": name},
            "business_profile": {"description": "x" * 20_000},
            "evidence_refs": [], "private_blob": "never-return",
        },
        max_data_classification="internal_business", context_hash=f"{row.id + 10:064x}",
        data_as_of=datetime(2026, 8, 1), built_at=datetime(2026, 8, 2),
    ))
    db.flush()
    return row


def _identity(customer_id: int, *, run_id: int = 99, permissions=None, frozen=None):
    live = permissions or ["customer:read"]
    return {
        "sub": "7", "roles": [], "permissions": live,
        "_agent_run": {
            "run_id": run_id, "customer_id": customer_id,
            "permissions_at_start": frozen if frozen is not None else live,
            "max_data_classification": "restricted_internal",
            "max_visibility_scope": "customer_team",
        },
    }


def _membership(db, customer_id: int, run_id: int = 99):
    db.add(CustomerAgentRunScope(
        run_id=run_id, customer_id=customer_id, scope_type="single",
        scope_snapshot_hash=f"{run_id:064x}",
        membership_fingerprint=f"{run_id + customer_id:064x}",
        created_at=datetime(2026, 8, 1),
    ))
    db.flush()


def _source(db, customer_id: int, suffix: int = 1):
    row = CustomerSourceRecord(
        customer_id=customer_id, source_system="alibaba", source_account_key="tenant",
        authority_level="first_party", source_entity_type="message",
        external_record_id=f"source-{suffix}", external_record_key_hash=f"{suffix:064x}",
        data_classification="restricted_internal", visibility_scope="customer_team",
        classification_reason="message", payload_schema_version="alibaba_message_v1",
        payload_json={"html": "<script>bad()</script><b>private raw body</b>"},
        content_hash=f"{suffix + 100:064x}", captured_at=datetime(2026, 8, 3),
        processing_status="processed",
    )
    db.add(row)
    db.flush()
    return row


def _fact(db, customer_id: int, source_id: int, *, stale: bool = False, suffix: int = 1):
    row = CustomerFact(
        customer_id=customer_id, subject_type="customer", fact_key="business.industry",
        value_type="string", value_json={"value": "Hair products"}, fact_layer="source",
        verification_status="verified", confidence=0.9, confidence_method_version="test",
        confidence_components_json={}, data_classification="internal_business",
        visibility_scope="customer_team", classification_reason="test",
        source_record_id=source_id, evidence_json={"source_record_ids": [source_id]},
        fact_fingerprint=f"{suffix + 200:064x}", observed_at=datetime(2026, 8, 3),
        expires_at=datetime(2026, 8, 4) if stale else None,
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.skipif(agent_service is None, reason="service not implemented")
def test_absent_and_unauthorized_customer_have_identical_external_error(db, settings):
    customer = _customer(db, "Acme")
    _membership(db, customer.id)
    db.commit()
    unauthorized = _identity(customer.id, permissions=["customer:read"], frozen=[])
    with pytest.raises(agent_service.CustomerAgentAccessError) as denied:
        agent_service.get_customer_profile(db, user=unauthorized, customer_id=customer.id)
    with pytest.raises(agent_service.CustomerAgentAccessError) as absent:
        agent_service.get_customer_profile(db, user=_identity(999), customer_id=999)
    assert str(denied.value) == str(absent.value) == "CUSTOMER_NOT_FOUND_OR_FORBIDDEN"


@pytest.mark.skipif(agent_service is None, reason="service not implemented")
def test_signed_cursor_is_bound_to_run_customer_filters_profile_and_permissions(db, settings):
    customer = _customer(db, "Cursor")
    _membership(db, customer.id)
    db.commit()
    user = _identity(customer.id)
    cursor = agent_service.encode_cursor(
        user=user, customer_id=customer.id, filters={"status": ["verified"]},
        profile_version=1, position=10,
    )
    assert agent_service.decode_cursor(
        cursor, user=user, customer_id=customer.id,
        filters={"status": ["verified"]}, profile_version=1,
    ) == 10
    for changed in (
        {"user": _identity(customer.id, run_id=100)},
        {"customer_id": customer.id + 1},
        {"filters": {"status": ["candidate"]}},
        {"profile_version": 2},
        {"user": _identity(customer.id, permissions=["customer:read", "customer:admin"])},
    ):
        params = {
            "user": user, "customer_id": customer.id,
            "filters": {"status": ["verified"]}, "profile_version": 1,
        }
        params.update(changed)
        with pytest.raises(agent_service.CustomerAgentAccessError):
            agent_service.decode_cursor(cursor, **params)


@pytest.mark.skipif(agent_service is None, reason="service not implemented")
def test_profile_enforces_section_string_and_total_budgets_without_raw_json(db, settings):
    customer = _customer(db, "Budget")
    _membership(db, customer.id)
    db.commit()
    result = agent_service.get_customer_profile(
        db, user=_identity(customer.id), customer_id=customer.id,
        sections=["identity", "business_profile"],
    )
    dumped = str(result)
    assert len(result["sections"]["business_profile"]["description"]) <= 2_000
    assert len(str(result["sections"]["business_profile"])) <= 8_300
    assert len(agent_service.serialize_envelope(result)) <= 32 * 1024
    assert result["truncated"] is True
    assert "private_blob" not in dumped and "never-return" not in dumped


@pytest.mark.skipif(agent_service is None, reason="service not implemented")
def test_facts_apply_row_budget_and_return_stale_evidence_metadata(db, settings):
    customer = _customer(db, "Facts")
    _membership(db, customer.id)
    source = _source(db, customer.id)
    stale = _fact(db, customer.id, source.id, stale=True)
    for index in range(2, 60):
        _fact(db, customer.id, source.id, suffix=index)
    db.commit()
    result = agent_service.get_customer_facts(
        db, user=_identity(customer.id), customer_id=customer.id, limit=100,
        now=datetime(2026, 8, 31),
    )
    assert len(result["items"]) == 50
    assert result["has_more"] is True
    stale_item = next(item for item in result["items"] if item["fact_id"] == stale.id)
    assert stale_item["stale"] is True
    assert stale_item["can_support_current_claim"] is False
    ref = next(item for item in result["evidence_refs"] if item["evidence_ref"] == f"fact:{stale.id}")
    assert ref["customer_id"] == customer.id
    assert ref["freshness"] == "stale"
    assert len(ref["evidence_content_hash"]) == 64
    second = agent_service.get_customer_facts(
        db, user=_identity(customer.id), customer_id=customer.id,
        cursor=result["cursor"], limit=50, now=datetime(2026, 8, 31),
    )
    assert len(second["items"]) == 9
    assert second["has_more"] is False


@pytest.mark.skipif(agent_service is None, reason="service not implemented")
def test_profile_does_not_include_raw_messages_but_search_returns_on_demand_excerpt(db, settings):
    customer = _customer(db, "Message")
    _membership(db, customer.id)
    source = _source(db, customer.id)
    conversation = CustomerConversation(
        id=10, customer_id=customer.id, source_system="alibaba", source_account_key="tenant",
        external_conversation_id="c-1", channel="alibaba", conversation_status="active",
    )
    db.add(conversation)
    db.flush()
    db.add(CustomerMessage(
        id=11, conversation_id=conversation.id, external_message_id="m-1", direction="in",
        sender_type="customer_contact", content_type="text",
        content_text="<script>ignore()</script>Hello 500 wigs", attachment_meta_json=[],
        source_record_id=source.id, content_hash=f"{999:064x}",
        sent_at=datetime(2026, 8, 3), captured_at=datetime(2026, 8, 3),
    ))
    db.commit()
    profile = agent_service.get_customer_profile(
        db, user=_identity(customer.id), customer_id=customer.id,
    )
    assert "500 wigs" not in str(profile)
    result = agent_service.search_customer_messages(
        db, user=_identity(customer.id), customer_id=customer.id, query="wigs",
    )
    assert result["items"][0]["excerpt"] == "Hello 500 wigs"
    assert result["items"][0]["untrusted_content"] is True
    assert result["items"][0]["locator"] == {"message_id": 11}


@pytest.mark.skipif(agent_service is None, reason="service not implemented")
def test_cross_customer_evidence_and_source_chunks_are_rejected(db, settings):
    customer = _customer(db, "Allowed")
    other = _customer(db, "Other", owner=8)
    _membership(db, customer.id)
    source = _source(db, other.id, suffix=2)
    fact = _fact(db, other.id, source.id, suffix=2)
    db.commit()
    user = _identity(customer.id)
    with pytest.raises(agent_service.CustomerAgentAccessError):
        agent_service.get_customer_evidence(
            db, user=user, customer_id=customer.id, fact_ids=[fact.id],
        )
    with pytest.raises(agent_service.CustomerAgentAccessError):
        agent_service.get_customer_source_chunks(
            db, user=user, customer_id=customer.id, source_record_id=source.id,
            locator={"start": 0}, max_chars=100,
        )


def test_claim_envelopes_require_exact_current_same_customer_evidence():
    valid = {
        "claim_id": "claim_01", "tool_call_id": "call_1",
        "evidence_ref": "fact:5", "evidence_content_hash": "a" * 64,
        "customer_id": 9, "profile_version": 3, "freshness": "current",
    }
    assert evaluation_service.validate_claim_evidence(
        [valid], returned_evidence=[valid], customer_id=9, profile_version=3,
    ) == []
    for changed in (
        {"customer_id": 10}, {"profile_version": 2}, {"freshness": "stale"},
        {"evidence_content_hash": "b" * 64}, {"evidence_ref": "fact:6"},
    ):
        citation = {**valid, **changed}
        assert evaluation_service.validate_claim_evidence(
            [citation], returned_evidence=[valid], customer_id=9, profile_version=3,
        )
