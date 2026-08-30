"""Secure, bounded Ark-only customer consumer tools."""

from datetime import date, datetime, timedelta
import importlib.util
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
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
from app.mcp.agent_tools import CustomerEvidenceInput
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAgentContext,
    CustomerAgentRunScope,
    CustomerAssignment,
    CustomerConversation,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerExternalIdentity,
    CustomerFact,
    CustomerMessage,
    CustomerObjectOwnership,
    CustomerOrder,
    CustomerOrderItem,
    CustomerProfileVersion,
    CustomerSourceRecord,
    CustomerSyncCursor,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        ArkUser.__table__, AgentRun.__table__, CustomerAccount.__table__,
        CustomerAssignment.__table__, CustomerProfileVersion.__table__,
        CustomerExternalIdentity.__table__,
        CustomerContactPoint.__table__,
        CustomerContactRelationship.__table__,
        CustomerAgentContext.__table__, CustomerSourceRecord.__table__,
        CustomerFact.__table__, CustomerConversation.__table__,
        CustomerMessage.__table__, CustomerOrder.__table__, CustomerOrderItem.__table__,
        CustomerAction.__table__, CustomerObjectOwnership.__table__,
        CustomerAgentRunScope.__table__, CustomerSyncCursor.__table__,
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


def _fact(
    db, customer_id: int, source_id: int, *, stale: bool = False, suffix: int = 1,
    fact_key: str = "business.industry", observed_at: datetime | None = None,
    expires_at: datetime | None = None,
):
    row = CustomerFact(
        customer_id=customer_id, subject_type="customer", fact_key=fact_key,
        value_type="string", value_json={"value": "Hair products"}, fact_layer="source",
        verification_status="verified", confidence=0.9, confidence_method_version="test",
        confidence_components_json={}, data_classification="internal_business",
        visibility_scope="customer_team", classification_reason="test",
        source_record_id=source_id, evidence_json={"source_record_ids": [source_id]},
        fact_fingerprint=f"{suffix + 200:064x}",
        observed_at=observed_at or datetime(2026, 8, 3),
        expires_at=expires_at or (datetime(2026, 8, 4) if stale else None),
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


def test_moved_conversation_raw_message_is_only_visible_to_logical_owner(db, settings):
    old = _customer(db, "Old conversation")
    new = _customer(db, "New conversation")
    _membership(db, old.id, run_id=91)
    _membership(db, new.id, run_id=92)
    source = _source(db, old.id, suffix=9)
    conversation = CustomerConversation(
        id=90, customer_id=old.id, source_system="alibaba", source_account_key="tenant",
        external_conversation_id="moved-c", channel="alibaba", conversation_status="active",
    )
    db.add(conversation)
    db.flush()
    db.add(CustomerMessage(
        id=91, conversation_id=conversation.id, external_message_id="moved-m", direction="in",
        sender_type="customer_contact", content_type="text", content_text="moved private body",
        attachment_meta_json=[], source_record_id=source.id, content_hash=f"{901:064x}",
        sent_at=datetime(2026, 8, 3), captured_at=datetime(2026, 8, 3),
    ))
    db.add(CustomerObjectOwnership(
        object_type="conversation", object_id=conversation.id,
        storage_customer_id=old.id, current_customer_id=new.id,
        ownership_version=1, last_change_proposal_id=999,
        last_action_type="split",
    ))
    db.commit()
    with pytest.raises(agent_service.CustomerAgentAccessError):
        agent_service.search_customer_messages(
            db, user=_identity(old.id, run_id=91), customer_id=old.id,
            conversation_id=conversation.id,
        )
    moved = agent_service.search_customer_messages(
        db, user=_identity(new.id, run_id=92), customer_id=new.id,
        conversation_id=conversation.id,
    )
    assert [item["message_id"] for item in moved["items"]] == [91]


def test_profile_freshness_uses_fact_and_source_policies(db, settings):
    customer = _customer(db, "Freshness")
    _membership(db, customer.id)
    db.add(CustomerExternalIdentity(
        customer_id=customer.id, source_system="okki", source_account_key="tenant",
        identifier_type="company_id", raw_value="old-stable-id",
        normalized_value="old-stable-id", identity_strength="strong",
        cardinality="one_to_one", auto_match_ceiling="verified",
        verification_status="verified", confidence=1,
        confidence_method_version="test", confidence_components_json={}, is_primary=True,
        first_seen_at=datetime(2020, 1, 1), last_seen_at=datetime(2020, 1, 1),
        verified_at=datetime(2020, 1, 1), status="active",
        identity_fingerprint=f"{991:064x}",
    ))
    fresh_source = _source(db, customer.id, suffix=21)
    fresh_source.captured_at = datetime(2026, 8, 30)
    stale_source = CustomerSourceRecord(
        customer_id=customer.id, source_system="okki", source_account_key="tenant",
        authority_level="transactional", source_entity_type="order",
        external_record_id="old-order", external_record_key_hash=f"{22:064x}",
        data_classification="internal_business", visibility_scope="customer_team",
        classification_reason="order", payload_schema_version="okki_order_v1",
        payload_json={"order": "old"}, content_hash=f"{122:064x}",
        captured_at=datetime(2026, 7, 1), processing_status="processed",
    )
    db.add(stale_source)
    db.flush()
    unavailable_source = CustomerSourceRecord(
        customer_id=customer.id, source_system="website", source_account_key="global",
        authority_level="official_company", source_entity_type="company_page",
        external_record_id="missing-sync", external_record_key_hash=f"{23:064x}",
        data_classification="public_business", visibility_scope="all_authorized",
        classification_reason="website", payload_schema_version="company_page_v1",
        payload_json={"page": "missing"}, content_hash=f"{123:064x}",
        captured_at=datetime(2026, 8, 20), processing_status="processed",
    )
    db.add(unavailable_source)
    db.flush()
    expired_fact = _fact(
        db, customer.id, fresh_source.id, suffix=21,
        expires_at=datetime(2026, 8, 20),
    )
    permanent_order_fact = _fact(
        db, customer.id, stale_source.id, suffix=22,
        fact_key="commercial.has_valid_order", observed_at=datetime(2020, 1, 1),
    )
    unavailable_fact = _fact(db, customer.id, unavailable_source.id, suffix=23)
    version = db.get(CustomerProfileVersion, customer.current_profile_version_id)
    version.evidence_fact_ids = [expired_fact.id, permanent_order_fact.id, unavailable_fact.id]
    db.add_all([
        CustomerSyncCursor(
            source_system="alibaba", resource_type="messages", scope_key="tenant",
            cursor_value="fresh", sync_status="idle", generation=1,
            last_success_at=datetime(2026, 8, 30), last_record_at=datetime(2026, 8, 30),
            last_counts_json={},
        ),
        CustomerSyncCursor(
            source_system="okki", resource_type="orders", scope_key="tenant",
            cursor_value="old", sync_status="idle", generation=1,
            last_success_at=datetime(2026, 7, 1), last_record_at=datetime(2026, 7, 1),
            last_counts_json={},
        ),
    ])
    db.commit()
    result = agent_service.get_customer_profile(
        db, user=_identity(customer.id), customer_id=customer.id,
        sections=["identity", "business_profile", "commercial_summary"],
        now=datetime(2026, 8, 31),
    )
    assert result["source_freshness_map"]["alibaba:messages:tenant"]["status"] == "fresh"
    assert result["source_freshness_map"]["okki:orders:tenant"]["status"] == "fresh"
    assert result["source_freshness_map"]["website:company_page:global"]["status"] == "unavailable"
    assert "website:company_page:global" in result["unavailable_sources"]
    assert result["stale_sections"] == ["business_profile"]


def test_budget_truncation_cursor_covers_every_fact_once_and_refs_match_items(db, settings):
    customer = _customer(db, "Paged budget")
    _membership(db, customer.id)
    source = _source(db, customer.id, suffix=31)
    expected = []
    for index in range(80):
        row = _fact(db, customer.id, source.id, suffix=100 + index)
        row.value_json = {"value": f"{index}:" + "x" * 4_000}
        expected.append(row.id)
    db.commit()
    cursor = None
    seen = []
    while True:
        page = agent_service.get_customer_facts(
            db, user=_identity(customer.id), customer_id=customer.id,
            cursor=cursor, limit=50,
        )
        item_ids = [item["fact_id"] for item in page["items"]]
        seen.extend(item_ids)
        assert {ref["evidence_ref"] for ref in page["evidence_refs"]} == {
            f"fact:{fact_id}" for fact_id in item_ids
        }
        if not page["has_more"]:
            break
        assert page["cursor"] and page["cursor"] != cursor
        cursor = page["cursor"]
    assert seen == expected


def test_single_row_over_total_budget_is_clipped_and_pagination_terminates(db, settings):
    customer = _customer(db, "Huge row budget")
    _membership(db, customer.id)
    source = _source(db, customer.id, suffix=41)
    expected = []
    for index in range(3):
        row = _fact(db, customer.id, source.id, suffix=200 + index)
        row.value_json = {f"field_{field:03d}": "x" * 2_000 for field in range(100)}
        expected.append(row.id)
    db.commit()

    cursor = None
    seen = []
    for _ in range(4):
        result = agent_service.get_customer_facts(
            db, user=_identity(customer.id), customer_id=customer.id,
            cursor=cursor, limit=2,
        )
        assert len(result["items"]) == 1
        assert len(agent_service.serialize_envelope(result)) <= 64 * 1024
        item = result["items"][0]
        assert item["truncated_fields"]
        seen.append(item["fact_id"])
        assert [ref["evidence_ref"] for ref in result["evidence_refs"]] == [
            f"fact:{item['fact_id']}"
        ]
        if not result["has_more"]:
            break
        assert result["cursor"] and result["cursor"] != cursor
        cursor = result["cursor"]
    assert seen == expected


def test_orders_require_internal_business_classification(db, settings):
    customer = _customer(db, "Public order")
    _membership(db, customer.id)
    source = _source(db, customer.id, suffix=77)
    db.add(CustomerOrder(
        customer_id=customer.id, source_system="okki", source_account_key="tenant",
        external_order_id="classified-order", order_status="confirmed",
        currency="USD", amount_original=100, amount_usd=100,
        is_valid_business_order=True,
        source_record_id=source.id,
        source_hash=f"{777:064x}", synced_at=datetime(2026, 8, 1),
    ))
    db.commit()
    public_user = _identity(customer.id)
    public_user["_agent_run"]["max_data_classification"] = "public_business"
    with pytest.raises(agent_service.CustomerAgentAccessError):
        agent_service.get_customer_orders(
            db, user=public_user, customer_id=customer.id,
        )


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


def test_customer_evidence_paginates_large_requested_set_without_loss(db, settings):
    customer = _customer(db, "Paged evidence")
    other = _customer(db, "Other paged evidence")
    _membership(db, customer.id, run_id=201)
    _membership(db, other.id, run_id=202)
    source = _source(db, customer.id, suffix=51)
    created = []
    for index in range(3):
        fact = _fact(db, customer.id, source.id, suffix=300 + index)
        fact.value_json = {f"field_{field:03d}": "x" * 2_000 for field in range(100)}
        created.append(fact.id)
    requested = [created[2], created[0], created[1]]
    db.commit()

    cursor = None
    seen = []
    while True:
        result = agent_service.get_customer_evidence(
            db, user=_identity(customer.id, run_id=201), customer_id=customer.id,
            fact_ids=requested, cursor=cursor,
        )
        item_ids = [item["fact_id"] for item in result["items"]]
        assert item_ids
        seen.extend(item_ids)
        assert [ref["evidence_ref"] for ref in result["evidence_refs"]] == [
            f"fact:{fact_id}" for fact_id in item_ids
        ]
        if not result["has_more"]:
            break
        assert result["cursor"] and result["cursor"] != cursor
        if cursor is None:
            with pytest.raises(agent_service.CustomerAgentAccessError):
                agent_service.get_customer_evidence(
                    db, user=_identity(customer.id, run_id=201), customer_id=customer.id,
                    fact_ids=list(reversed(requested)), cursor=result["cursor"],
                )
            with pytest.raises(agent_service.CustomerAgentAccessError):
                agent_service.get_customer_evidence(
                    db, user=_identity(other.id, run_id=202), customer_id=other.id,
                    fact_ids=requested, cursor=result["cursor"],
                )
        cursor = result["cursor"]
    assert seen == requested


def test_customer_evidence_mcp_input_accepts_signed_cursor():
    params = CustomerEvidenceInput(customer_id=7, fact_ids=[3, 1], cursor="signed")
    assert params.model_dump(exclude_none=True) == {
        "customer_id": 7, "fact_ids": [3, 1], "cursor": "signed",
    }


def test_profile_budget_prunes_large_source_metadata_or_fails_closed(settings):
    result = agent_tool_contract.envelope(profile_version=1, data_as_of=None)
    result.update({
        "source_freshness_map": {
            f"source:{index}": {"status": "unavailable", "detail": "x" * 2_000}
            for index in range(100)
        },
        "unavailable_sources": [f"source:{index}" for index in range(100)],
        "stale_sections": [f"section:{index}" for index in range(100)],
    })
    fitted = agent_tool_contract.fit(result, max_bytes=32 * 1024)
    assert len(agent_tool_contract.serialize_envelope(fitted)) <= 32 * 1024
    assert fitted["truncated"] is True
    with pytest.raises(ValueError, match="OUTPUT_BUDGET_EXCEEDED"):
        agent_tool_contract.fit(
            agent_tool_contract.envelope(profile_version=1, data_as_of=None), max_bytes=8,
        )


def test_message_keyset_cursor_ignores_newer_insert_between_pages(db, settings):
    customer = _customer(db, "Message keyset")
    _membership(db, customer.id)
    source = _source(db, customer.id, suffix=61)
    conversation = CustomerConversation(
        customer_id=customer.id, source_system="alibaba", source_account_key="tenant",
        external_conversation_id="keyset-c", channel="alibaba", conversation_status="active",
    )
    db.add(conversation)
    db.flush()
    for message_id, day in ((610, 30), (611, 20), (612, 10)):
        db.add(CustomerMessage(
            id=message_id, conversation_id=conversation.id,
            external_message_id=f"keyset-{message_id}", direction="in",
            sender_type="customer_contact", content_type="text",
            content_text=f"message-{day}", attachment_meta_json=[],
            source_record_id=source.id, content_hash=f"{message_id:064x}",
            sent_at=datetime(2026, 8, day), captured_at=datetime(2026, 8, day),
        ))
    db.commit()
    first = agent_service.search_customer_messages(
        db, user=_identity(customer.id), customer_id=customer.id, limit=1,
    )
    db.add(CustomerMessage(
        id=613, conversation_id=conversation.id, external_message_id="keyset-new",
        direction="in", sender_type="customer_contact", content_type="text",
        content_text="newer insert", attachment_meta_json=[], source_record_id=source.id,
        content_hash=f"{613:064x}", sent_at=datetime(2026, 8, 31),
        captured_at=datetime(2026, 8, 31),
    ))
    db.commit()
    second = agent_service.search_customer_messages(
        db, user=_identity(customer.id), customer_id=customer.id,
        cursor=first["cursor"], limit=1,
    )
    assert [item["message_id"] for item in first["items"] + second["items"]] == [610, 611]


def test_keyset_cursor_accepts_same_date_filter_on_next_page(db, settings):
    customer = _customer(db, "Order date cursor")
    _membership(db, customer.id)
    source = _source(db, customer.id, suffix=615)
    for index in range(2):
        db.add(CustomerOrder(
            customer_id=customer.id, source_system="okki", source_account_key="tenant",
            external_order_id=f"date-cursor-{index}", order_no=f"DATE-{index}",
            order_status="confirmed", account_date=date(2026, 8, 20 - index),
            currency="USD", amount_original=100, amount_usd=100,
            is_valid_business_order=True, source_record_id=source.id,
            source_hash=f"{6150 + index:064x}", synced_at=datetime(2026, 8, 20),
        ))
    db.commit()
    first = agent_service.get_customer_orders(
        db, user=_identity(customer.id), customer_id=customer.id,
        date_from=date(2026, 8, 1), limit=1,
    )
    second = agent_service.get_customer_orders(
        db, user=_identity(customer.id), customer_id=customer.id,
        date_from=date(2026, 8, 1), cursor=first["cursor"], limit=1,
    )
    assert len(first["items"] + second["items"]) == 2


def test_dynamic_queries_do_not_apply_global_10001_row_cap(db, settings):
    customer = _customer(db, "No global cap")
    _membership(db, customer.id)
    source = _source(db, customer.id, suffix=62)
    _fact(db, customer.id, source.id, suffix=620)
    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if "ark_customer_facts" in statement:
            statements.append((statement, parameters))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        agent_service.get_customer_facts(
            db, user=_identity(customer.id), customer_id=customer.id, limit=1,
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    assert "10001" not in repr(statements)


def test_orders_batch_load_current_page_items_once(db, settings):
    customer = _customer(db, "Order batch")
    _membership(db, customer.id)
    source = _source(db, customer.id, suffix=63)
    for index in range(3):
        order = CustomerOrder(
            customer_id=customer.id, source_system="okki", source_account_key="tenant",
            external_order_id=f"batch-{index}", order_no=f"SO-{index}",
            order_status="confirmed", account_date=date(2026, 8, 10 - index),
            currency="USD", amount_original=100, amount_usd=100,
            is_valid_business_order=True, source_record_id=source.id,
            source_hash=f"{700 + index:064x}", synced_at=datetime(2026, 8, 1),
        )
        db.add(order)
        db.flush()
        db.add(CustomerOrderItem(
            order_id=order.id, external_item_id=f"item-{index}",
            product_name="Wig", quantity=1, quantity_unit="pcs", item_type="bulk",
            source_record_id=source.id, item_fingerprint=f"{800 + index:064x}",
        ))
    db.commit()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if "FROM ark_customer_order_items" in statement:
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = agent_service.get_customer_orders(
            db, user=_identity(customer.id), customer_id=customer.id,
            include_items=True, limit=3,
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    assert len(result["items"]) == 3
    assert len(statements) == 1
    assert "LIMIT" in statements[0].upper()


def test_profile_freshness_loads_all_sync_cursors_once(db, settings):
    customer = _customer(db, "Freshness batch")
    _membership(db, customer.id)
    version = db.get(CustomerProfileVersion, customer.current_profile_version_id)
    fact_ids = []
    for index in range(3):
        source = _source(db, customer.id, suffix=70 + index)
        source.source_account_key = f"tenant-{index}"
        fact_ids.append(_fact(db, customer.id, source.id, suffix=70 + index).id)
        db.add(CustomerSyncCursor(
            source_system="alibaba", resource_type="messages", scope_key=f"tenant-{index}",
            cursor_value="ok", sync_status="idle", generation=1,
            last_success_at=datetime(2026, 8, 30), last_record_at=datetime(2026, 8, 30),
            last_counts_json={},
        ))
    version.evidence_fact_ids = fact_ids
    db.commit()
    count = 0

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal count
        if "FROM ark_customer_sync_cursors" in statement:
            count += 1

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        agent_service.get_customer_profile(
            db, user=_identity(customer.id), customer_id=customer.id,
            sections=["business_profile"], now=datetime(2026, 8, 31),
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    assert count == 1


def test_identifier_search_respects_classification_and_logical_owner(db, settings):
    customer = _customer(db, "Contact search")
    moved_to = _customer(db, "Moved contact target", owner=8)
    _membership(db, customer.id)
    restricted = CustomerContactPoint(
        customer_id=customer.id, point_type="email", raw_value="secret@example.com",
        normalized_value="secret@example.com", verification_status="valid",
        contactability_status="allowed", is_primary=True,
        data_classification="personal_contact", point_fingerprint=f"{901:064x}",
        first_seen_at=datetime(2026, 8, 1), last_seen_at=datetime(2026, 8, 1),
    )
    moved = CustomerContactPoint(
        customer_id=customer.id, point_type="whatsapp", raw_value="+15550001",
        normalized_value="+15550001", verification_status="valid",
        contactability_status="allowed", is_primary=True,
        data_classification="internal_business", point_fingerprint=f"{902:064x}",
        first_seen_at=datetime(2026, 8, 1), last_seen_at=datetime(2026, 8, 1),
    )
    db.add_all([restricted, moved])
    db.flush()
    db.add(CustomerObjectOwnership(
        object_type="contact_point", object_id=moved.id,
        storage_customer_id=customer.id, current_customer_id=moved_to.id,
        ownership_version=1, last_change_proposal_id=999, last_action_type="split",
    ))
    db.commit()
    internal_user = _identity(customer.id)
    internal_user["_agent_run"]["max_data_classification"] = "internal_business"
    assert agent_service.search_customers(
        db, user=internal_user, keyword="secret@example.com", identifier_type="email",
    )["items"] == []
    assert agent_service.search_customers(
        db, user=internal_user, keyword="+15550001", identifier_type="whatsapp",
    )["items"] == []


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
