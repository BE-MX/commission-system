"""Bad optional evidence must not discard the human-reviewed draft."""
import pytest
from app.whatsapp_translation import reply_service, reply_state
from tests.reply_support import seed_reply, request, mock_model, output

@pytest.mark.parametrize("bad", [
    {"kind": "need", "status": "confirmed", "summary": "20 units", "message_index": 999, "quote": "20 units"},
    {"kind": "need", "status": "confirmed", "summary": "20 units", "message_index": 0, "quote": "fabricated quote"},
])
def test_invalid_optional_evidence_preserves_reply_and_prevents_record_write(db, monkeypatch, bad):
    identity, *_ = seed_reply(db, monkeypatch)
    reply_state.reply_cache.clear()
    mock_model(monkeypatch, planner={"memory_changes": [bad]})
    result = reply_service.suggest_reply(db, identity, request())
    assert result.reply_text == output()["reply_text"] and result.status == "ready"
    assert result.memory_error == "reply_memory_update_failed"
    assert result.memory_update == []
