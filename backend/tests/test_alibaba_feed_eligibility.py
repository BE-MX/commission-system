"""Qualification is truthful even when all automatic execution stays disabled."""
from app.alibaba_feed.eligibility import rule_eligibility
from app.core.config import get_settings
from tests.test_alibaba_feed_core import NOW
from tests.test_alibaba_feed_v11_normalization import v11_store, v11_payload, process  # noqa: F401


def authorize(store):
    db, source = store
    source.crm_shared = source.private_feed_enabled = source.ai_egress_allowed = True
    source.verified_capabilities = {name: True for name in ("stable_message_ids", "reliable_order", "latest_coverage", "human_identity", "activity_scan", "deletions")}
    source.verified_capabilities = source.verified_capabilities | {"evidence_note": "Synthetic verification only"}
    db.commit()
    return source


def test_qualified_prerequisites_never_override_disabled_execution(v11_store, monkeypatch):
    source = authorize(v11_store)
    item = process(v11_store, v11_payload())
    monkeypatch.setattr(get_settings(), "ALIBABA_FEED_AUTOMATION_ENABLED", False)
    gates = rule_eligibility(v11_store[0], item, source, user_id=1, now=NOW)
    assert gates["qualified"]["reply_rules"]
    assert gates["qualified"]["routine_ai"]
    assert not gates["enabled"] and not any(gates["allowed"].values())
    assert "AUTOMATION_DISABLED" in gates["reasons"]


def test_newer_incomplete_conversation_cannot_reuse_older_complete_tail(v11_store):
    source = authorize(v11_store)
    old = process(v11_store, v11_payload())
    newer = v11_payload("partial-new", conversation_revision=2)
    newer["records"][0].update(inquiry_id="second-inquiry", type="tm")
    newer["records"][0]["coverage"].update(history_complete=False, latest_complete=False, has_more=True)
    process(v11_store, newer)
    gates = rule_eligibility(v11_store[0], old, source, user_id=1, now=NOW)
    assert gates["latest_qualified_conversation_revision"] == 2
    assert not gates["qualified"]["reply_rules"] and not gates["qualified"]["routine_ai"]
    assert "LATEST_COVERAGE_REQUIRED" in gates["reasons"]


def test_unknown_actor_does_not_qualify_reply_rules(v11_store):
    source = authorize(v11_store)
    data = v11_payload()
    data["records"][0]["messages"][0]["actor_type"] = "unknown"
    item = process(v11_store, data)
    gates = rule_eligibility(v11_store[0], item, source, user_id=1, now=NOW)
    assert not gates["qualified"]["reply_rules"]
    assert "ROLE_SEMANTICS_UNVERIFIED" in gates["reasons"]


def test_collector_coverage_claim_needs_server_capability_evidence(v11_store):
    source = authorize(v11_store)
    source.verified_capabilities = {}
    v11_store[0].commit()
    item = process(v11_store, v11_payload())
    gates = rule_eligibility(v11_store[0], item, source, user_id=1, now=NOW)
    assert not any(gates["qualified"].values())
    assert "CAPABILITY_EVIDENCE_REQUIRED" in gates["reasons"]


def test_stale_or_missing_coverage_interval_stays_unqualified(v11_store):
    source = authorize(v11_store)
    data = v11_payload()
    data["records"][0]["coverage"]["covered_through"] = None
    item = process(v11_store, data)
    assert not rule_eligibility(v11_store[0], item, source, user_id=1, now=NOW)["qualified"]["reply_rules"]


def test_automatic_execution_also_requires_current_pilot_enrollment(v11_store, monkeypatch):
    source = authorize(v11_store)
    item = process(v11_store, v11_payload())
    settings = get_settings()
    for name in ("ALIBABA_FEED_AUTOMATION_ENABLED", "CLIENT_DESK_ENABLED"):
        monkeypatch.setattr(settings, name, True)
    monkeypatch.setattr(settings, "CLIENT_DESK_PILOT_USER_IDS", [])
    assert not rule_eligibility(v11_store[0], item, source, user_id=1, now=NOW)["allowed"]["reply_rules"]
    monkeypatch.setattr(settings, "CLIENT_DESK_PILOT_USER_IDS", [1])
    assert rule_eligibility(v11_store[0], item, source, user_id=1, now=NOW)["allowed"]["reply_rules"]
