"""Private-sea board: research report, stage, AI tags and the controlled agent loop."""

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.client_desk import agent_tools, board, pack, runner, service, validator
from app.client_desk.models import ClientDeskState as State, ClientDeskSuggestion as Row
from app.client_desk.schemas import TagPut
from app.system.models import SysDict
from tests.test_client_desk_engine import db, configured, source, queued, valid, NOW, DAY

RESEARCH = {
    "schema_version": "customer_research_v1",
    "input_hash": "0" * 64,
    "claims": [
        {"claim_id": "claim_a", "section": "identity", "statement": "Studio in Osaka", "citation_ids": ["citation_a"]},
        {"claim_id": "claim_b", "section": "strategy", "statement": "Offer a sample kit", "citation_ids": ["citation_b"]},
    ],
    "citations": [{"citation_id": "citation_a"}, {"citation_id": "citation_b"}],
}
GAP = {
    "schema_version": "research_gap_v1",
    "input_hash": "0" * 64,
    "gap_reason": "Only a name was available, nothing verified",
    "missing_information": ["website"],
}


def test_research_report_hides_gap_and_raw_documents():
    assert board.research_report([]) == {"status": "none"}
    assert board.research_report([{"id": "1", "result": GAP}]) == {"status": "none"}
    assert board.research_report([{"id": "1", "result": "raw text"}]) == {"status": "none"}
    report = board.research_report(
        [{"id": "2", "result": GAP}, {"id": "3", "result": RESEARCH, "event_key": "research:3"}]
    )
    assert report["status"] == "ready" and report["verdict"] == "Offer a sample kit"
    assert [s["key"] for s in report["sections"]] == ["identity", "strategy"]
    flat = json.dumps(report, default=str)
    assert "gap_reason" not in flat and "input_hash" not in flat and "citation_id" not in flat
    compact = board.model_research(report)
    assert set(compact) == {"verdict", "sections"}


@pytest.mark.parametrize(
    "orders,last_order,touch,created,expected",
    [
        (3, date(2026, 9, 1), None, None, "repeat"),
        (1, date(2026, 9, 1), date(2026, 11, 1), None, "active"),
        (2, date(2025, 1, 1), None, None, "churn"),
        (0, None, None, datetime(2026, 10, 1), "nurture"),
        (1, date(2026, 6, 1), date(2026, 8, 1), None, "dormant"),
    ],
)
def test_stage_is_deterministic(orders, last_order, touch, created, expected):
    assert board.compute_stage(orders, last_order, touch, created, DAY) == expected


def seed(db):
    board.seed_tag_dictionary(db)
    db.commit()


def test_tag_vocabulary_seeded_from_dictionary_and_inactive_codes_drop(db):
    seed(db)
    vocab = board.tag_vocabulary(db)
    assert {"ai", "risk", "type"} == set(vocab)
    assert "high_repurchase" in [t["code"] for t in vocab["ai"]]
    db.query(SysDict).filter_by(code="high_repurchase").update({"is_active": False})
    db.commit()
    state = State(ai_tags=[{"code": "high_repurchase"}, {"code": "complaint"}])
    assert [t["code"] for t in board.effective_tags(state, board.tag_vocabulary(db))] == ["complaint"]
    state.tag_overrides = ["complaint"]
    assert board.effective_tags(state, board.tag_vocabulary(db)) == []
    assert board.effective_tags(state, board.tag_vocabulary(db), valid=False) == []


def test_validator_rejects_unknown_tags_and_uncited_profile():
    p = pack.build_pack(source(), {}, [], DAY, tags=[{"code": "custom_need", "label": "定制", "kind": "ai"}])
    ok = valid() | {
        "tags": [{"code": "custom_need", "reason": "asked for custom", "cites": ["M-1"]}],
        "profile": {"needs": {"text": "Custom wigs", "cites": ["M-1"]}},
    }
    out = validator.validate(json.dumps(ok), p, DAY)
    assert out["tags"][0]["cites"][0]["event_key"] == "wa:a:2026-11-04"
    assert out["profile"]["needs"]["text"] == "Custom wigs"
    for bad in [
        {"tags": [{"code": "invented", "reason": "x", "cites": ["M-1"]}]},
        {"tags": [{"code": "custom_need", "reason": "x", "cites": ["O-9"]}]},
        {"profile": {"needs": {"text": "x", "cites": ["O-9"]}}},
        {"profile": {"needs": {"text": "pay https://evil.example", "cites": ["M-1"]}}},
    ]:
        with pytest.raises(ValueError):
            validator.validate(json.dumps(valid() | bad), p, DAY)


def mock_model(monkeypatch, replies, sent):
    monkeypatch.setattr(
        runner,
        "prepare_text_chat",
        lambda *a: SimpleNamespace(provider=SimpleNamespace(id=5), preset=SimpleNamespace(system_prompt=None)),
    )

    def chat(db, **params):
        sent.append(params["messages"])
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"content": reply}

    monkeypatch.setattr(runner, "chat", chat)


def material(**extra):
    hidden = {"key": "M-9", "event_key": "wa:a:2026-10-01", "text": "older ask about custom lace", "at": datetime(2026, 10, 1), "direction": "inbound"}
    return source(messages=[hidden], **extra)


def final_with_tag():
    return json.dumps(
        valid()
        | {
            "tags": [{"code": "custom_need", "reason": "asked", "cites": ["M-9"]}],
            "profile": {"needs": {"text": "Custom lace", "cites": ["M-9"]}},
        }
    )


def test_agent_reads_tool_then_applies_tags_automatically(db, configured, monkeypatch):
    seed(db)
    db.add(State(user_id=1, company_id=1, manual_version=0, tag_overrides=["complaint"]))
    db.commit()
    row = queued(db, run_seq=1, rule_codes=[])
    monkeypatch.setattr(runner.sources, "analysis_input", lambda *a, **k: material())
    sent = []
    replies = [json.dumps({"tool": "older_messages", "args": {"limit": 5}}), final_with_tag()]
    mock_model(monkeypatch, replies, sent)
    runner.run_job(db, runner.claim(db, NOW))
    state = db.query(State).one()
    assert row.status == "succeeded" and len(sent) == 2
    # The tool result is a later user turn and contains the hidden message.
    assert "older ask about custom lace" in sent[1][-1]["content"]
    assert [t["tool"] for t in row.agent_trace] == ["older_messages", "final"]
    assert [t["code"] for t in state.ai_tags] == ["custom_need"]
    assert state.profile_json["blocks"]["needs"]["text"] == "Custom lace"
    assert state.profile_dependencies["deps"] == {"proof": 1}
    assert row.protocol_version == "desk_v2"


def test_removed_tag_is_not_reapplied_and_vocabulary_excludes_it(db, configured, monkeypatch):
    seed(db)
    db.add(State(user_id=1, company_id=1, manual_version=0, tag_overrides=["custom_need"]))
    db.commit()
    queued(db, run_seq=1, rule_codes=[])
    monkeypatch.setattr(runner.sources, "analysis_input", lambda *a, **k: material())
    sent = []
    bad = json.dumps(valid() | {"tags": [{"code": "custom_need", "reason": "x", "cites": ["M-1"]}]})
    mock_model(monkeypatch, [bad, json.dumps(valid())], sent)
    runner.run_job(db, runner.claim(db, NOW))
    assert '"custom_need"' not in sent[0][-1]["content"]
    # The removed code is not offered; emitting it fails validation and one correction follows.
    assert len(sent) == 2 and runner.CORRECTION in sent[1][-1]["content"]
    state = db.query(State).one()
    assert state.ai_tags == [] and state.tag_overrides == ["custom_need"]


def test_step_budget_forces_final_and_uncertain_call_is_ambiguous(db, configured, monkeypatch):
    seed(db)
    row = queued(db, run_seq=0)
    configured.CLIENT_DESK_RULES = {"agent": {"routine_tool_steps": 1}}
    monkeypatch.setattr(runner.sources, "analysis_input", lambda *a, **k: material(conversations=[{"direction": "inbound", "last_at": NOW}]))
    sent = []
    tool = json.dumps({"tool": "research_detail"})
    mock_model(monkeypatch, [tool, tool, TimeoutError()], sent)
    runner.run_job(db, runner.claim(db, NOW))
    # Second tool request after the budget is treated as an invalid final answer,
    # the correction call times out and the run is never retried.
    assert len(sent) == 3 and row.status == "ambiguous"
    assert row.agent_trace[0]["status"] == "empty"


def test_inquiry_tool_requires_manual_selection():
    payload, refs, status = agent_tools.run_tool(None, source(), {}, "selected_inquiries", {})
    assert status == "empty" and refs == {}
    feed = source(analysis_policy="manual_only_v1")
    feed["refs"]["AF-7-1"] = {"source": "alibaba_feed", "event_key": "alibaba_feed:7:1", "text": "need 50 units", "at": "x"}
    payload, refs, status = agent_tools.run_tool(None, feed, {}, "selected_inquiries", {})
    assert status == "ok" and "AF-7-1" in refs
    payload, refs, status = agent_tools.run_tool(None, source(orders=[]), {}, "order_items", {"order_id": "99"})
    assert status == "rejected"


def test_manual_tag_toggle_validates_dictionary(db, monkeypatch):
    seed(db)
    monkeypatch.setattr(service, "scoped", lambda *a, **k: {"sub": "1"})
    monkeypatch.setattr(board, "stored_linkage_valid", lambda *a, **k: True)
    state = service.lock_state(db, 1, 5)
    state.ai_tags = [{"code": "custom_need"}]
    db.commit()
    out = service.set_tag(db, {"sub": "1"}, 5, TagPut(code="custom_need", action="remove"))
    assert out["ai_tags"] == [] and out["removed_tags"][0]["code"] == "custom_need"
    out = service.set_tag(db, {"sub": "1"}, 5, TagPut(code="custom_need", action="restore"))
    assert [t["code"] for t in out["ai_tags"]] == ["custom_need"]
    assert state.manual_version == 0
    with pytest.raises(HTTPException) as err:
        service.set_tag(db, {"sub": "1"}, 5, TagPut(code="unknown", action="remove"))
    assert err.value.status_code == 422


def test_board_projects_cards_stage_and_hides_tags_after_link_revoked(monkeypatch):
    from sqlalchemy import text
    from tests.test_client_desk_business import isolated as business_fixture
    from app.client_desk import source_context

    gen = business_fixture.__wrapped__(monkeypatch)
    db = next(gen)
    try:
        monkeypatch.setattr(board, "_current_linkage", lambda *a: ({}, set()))
        monkeypatch.setattr(source_context, "list_last_touches", lambda *a: {})
        monkeypatch.setattr("app.client_desk.access.require_enabled", lambda *a, **k: {"sub": "1"})
        monkeypatch.setattr("app.order_intelligence.service.VALID_ORDER_SQL", "1=1")
        seed(db)
        db.add(State(user_id=1, company_id=801, manual_version=0,
                     ai_tags=[{"code": "custom_need"}],
                     profile_dependencies={"deps": {"wa": []}}))
        db.commit()
        out = board.board(db, {"sub": "1"})
        card = out["items"][0]
        assert out["total"] == 1 and card["company_id"] == "801"
        assert card["orders"]["count"] == 2 and card["orders"]["amount_usd"] == 20
        assert card["contact_name"] == "Anna" and card["stage"] in dict(board.STAGES)
        assert "custom_need" in [t["code"] for t in card["tags"]]
        state = db.query(State).one()
        state.profile_dependencies = {"deps": {"wa": [{"account": "a", "link": 1, "version": 1, "generation": 1, "ai": True}]}}
        db.commit()
        card = board.board(db, {"sub": "1"})["items"][0]
        assert "custom_need" not in [t["code"] for t in card["tags"]]
        assert board.board(db, {"sub": "1"}, keyword="nomatch")["items"] == []
    finally:
        gen.close()
