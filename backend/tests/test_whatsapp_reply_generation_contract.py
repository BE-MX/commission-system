"""Direct-generation contracts replace citation rejection and fixed planner calls."""
import json
import pytest
from app.whatsapp_translation import reply_service, reply_state
from app.whatsapp_translation.errors import WhatsAppTranslationError
from tests.reply_support import mock_model, output, request, seed_reply

@pytest.fixture
def configured(db, monkeypatch):
    reply_state.reply_cache.clear()
    return seed_reply(db, monkeypatch)

@pytest.mark.parametrize("text", [
    "Thanks for your message today.", "You mentioned USD 100 as your budget.",
    "I cannot guarantee delivery.", "Catalog: https://example.com/catalog",
    "20 models, 10 pieces each means 200 pieces.", "Which size do you need?",
])
def test_content_is_editable_not_rejected_by_semantic_rules(db, monkeypatch, configured, text):
    calls = mock_model(monkeypatch, generator=output(reply_text=text, claims=[{"source_index": 999, "quote": "bad"}]))
    result = reply_service.suggest_reply(db, configured[0], request())
    assert result.status == "ready" and result.reply_text == text
    assert len(calls) == 1
    assert result.claims == []  # Model citations are no longer presented as verified.

@pytest.mark.parametrize("purpose", ["method", "constraint", "public_fact"])
def test_source_purpose_reaches_agent_without_forced_citation_schema(db, monkeypatch, configured, purpose):
    configured[-1].WHATSAPP_REPLY_SOURCE_BINDINGS[1]["purpose"] = purpose
    calls = mock_model(monkeypatch)
    reply_service.suggest_reply(db, configured[0], request())
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert payload["sources"][1]["purpose"] == purpose
    assert "allowed_fact_source_indices" not in payload
    assert "claims" not in payload.get("schema", {}).get("required", [])

def test_more_than_forty_rounds_reach_single_agent_call_in_order(db, monkeypatch, configured):
    messages = [{"role": "customer" if i % 2 == 0 else "salesperson", "text": f"message {i}", "timestamp": f"day {i // 20}"} for i in range(160)]
    calls = mock_model(monkeypatch)
    payload = request(messages=messages, context_scope={"requested_limit": 2000})
    result = reply_service.suggest_reply(db, configured[0], payload)
    data = json.loads(calls[0]["messages"][1]["content"])
    assert len(calls) == 1 and result.context_processing == "full"
    assert data["conversation"]["messages"] == payload.model_dump()["messages"]

def test_optional_blank_or_invalid_bookkeeping_never_suppresses_draft(db, monkeypatch, configured):
    calls = mock_model(monkeypatch, generator=output(meaning_zh="   ", rationale_zh="\n", missing_information=None),
                       planner={"memory_changes": [{"invalid": "optional"}]})
    result = reply_service.suggest_reply(db, configured[0], request())
    assert result.reply_text == output()["reply_text"] and result.status == "ready"
    assert result.meaning_zh.strip() and len(calls) == 1

def test_long_history_is_explicitly_summarized_without_dropping_chunks(db, monkeypatch, configured):
    calls = []
    def model(db, **kwargs):
        data = json.loads(kwargs["messages"][1]["content"]); calls.append(data)
        if data.get("task") == "summarize_history":
            return {"content": json.dumps({"summary": "Synthetic complete chunk summary"})}
        return {"content": json.dumps(output())}
    monkeypatch.setattr(reply_service, "chat", model)
    messages = [{"role": "customer", "text": str(i) + "x" * 1500} for i in range(30)]
    result = reply_service.suggest_reply(db, configured[0], request(messages=messages, context_scope={"requested_limit": 2000}))
    assert result.context_processing == "summarized"
    seen = {part["message_index"] for call in calls[:-1] for part in call["messages"]}
    assert seen == set(range(30))
    assert calls[-1]["conversation"]["history_summaries"]
    assert sum(len(m["text"]) for m in calls[-1]["conversation"]["messages"]) <= 8000

@pytest.mark.parametrize("action,segments", [("reply", ["Hi!", "Which size works for you? 🙂"]), ("wait", []), ("handoff", [])])
def test_auto_reply_contract(db, monkeypatch, configured, action, segments):
    calls = mock_model(monkeypatch, generator=output(auto_action=action, reply_segments=segments))
    result = reply_service.suggest_reply(db, configured[0], request(mode="auto"))
    assert result.auto_action == action and result.reply_segments == segments
    assert "后台系统提示词" in calls[0]["messages"][0]["content"]
    assert json.loads(calls[0]["messages"][1]["content"])["conversation"]["mode"] == "auto"
    if action == "reply":
        assert result.reply_text == "\n\n".join(segments)

@pytest.mark.parametrize("fields", [{}, {"auto_action": "reply", "reply_segments": []},
    {"auto_action": "reply", "reply_segments": ["x" * 401]}, {"auto_action": "reply", "reply_segments": ["x"] * 4},
    {"auto_action": "wait", "reply_segments": ["unexpected"]}])
def test_auto_missing_or_oversize_protocol_never_becomes_sendable(db, monkeypatch, configured, fields):
    mock_model(monkeypatch, generator=output(**fields))
    with pytest.raises(WhatsAppTranslationError) as exc:
        reply_service.suggest_reply(db, configured[0], request(mode="auto"))
    assert exc.value.error_code == "reply_invalid_response"
