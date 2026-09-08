"""Generation requests must describe the same citation boundary as the guard."""
import json

import pytest
from jsonschema import Draft202012Validator

from app.whatsapp_translation import reply_service, reply_state
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.reply_schemas import ReplyOutput, generation_schema
from tests.reply_support import mock_model, output, request, seed_reply


@pytest.fixture
def setup_reply(db, monkeypatch):
    reply_state.reply_cache.clear()
    yield seed_reply(db, monkeypatch)
    reply_state.reply_cache.clear()


def clarification():
    return output(status="needs_confirmation", claims=[],
                  reply_text="Which installation method would you like to test?",
                  meaning_zh="您希望测试哪种安装方式？")


@pytest.mark.parametrize("purpose", ["method", "constraint"])
def test_no_public_facts_require_empty_claims_in_generation_request(db, setup_reply, monkeypatch, purpose):
    identity, *_, settings = setup_reply
    settings.WHATSAPP_REPLY_SOURCE_BINDINGS[1]["purpose"] = purpose
    calls = mock_model(monkeypatch, generator=clarification())
    result = reply_service.suggest_reply(db, identity, request())
    payload = json.loads(calls[1]["messages"][1]["content"])
    assert payload["allowed_fact_source_indices"] == []
    assert payload["schema"]["properties"]["claims"]["maxItems"] == 0
    assert "claims" in payload["schema"]["required"]
    assert [s["source_index"] for s in payload["sources"]] == list(range(len(result.sources)))
    assert result.claims == [] and "no_public_facts" in result.risk_flags
    assert len(calls) == 2


def test_public_fact_schema_uses_original_source_index_not_filtered_index(db, setup_reply, monkeypatch):
    calls = mock_model(monkeypatch)
    result = reply_service.suggest_reply(db, setup_reply[0], request())
    payload = json.loads(calls[1]["messages"][1]["content"])
    assert payload["allowed_fact_source_indices"] == [1]
    assert payload["sources"][0]["source_index"] == 0
    assert payload["sources"][1]["source_index"] == 1
    assert payload["schema"]["$defs"]["ReplyClaim"]["properties"]["source_index"]["enum"] == [1]
    assert result.claims[0].source_index == 1


@pytest.mark.parametrize("bad_index", [0, 1, 5])
def test_disobedient_model_is_still_rejected_without_retry_or_stripping_claims(db, setup_reply, monkeypatch, bad_index):
    identity, *_, settings = setup_reply
    settings.WHATSAPP_REPLY_SOURCE_BINDINGS[1]["purpose"] = "method"
    invalid = output()
    invalid["claims"][0]["source_index"] = bad_index
    calls = mock_model(monkeypatch, generator=invalid)
    with pytest.raises(WhatsAppTranslationError) as caught:
        reply_service.suggest_reply(db, identity, request())
    assert caught.value.error_code == "reply_invalid_evidence"
    assert len(calls) == 2


def test_generation_schemas_are_valid_narrowed_and_request_local():
    original = ReplyOutput.model_json_schema()
    no_facts = generation_schema([])
    mixed = generation_schema([1, 4])
    for schema in (no_facts, mixed):
        Draft202012Validator.check_schema(schema)
    empty_validator = Draft202012Validator(no_facts)
    assert empty_validator.is_valid(clarification())
    assert not empty_validator.is_valid(output())
    mixed_validator = Draft202012Validator(mixed)
    assert mixed_validator.is_valid(clarification())  # No forced citation.
    for index in (0, 1, 2, 3, 4, 5):
        value = output()
        value["claims"][0]["source_index"] = index
        assert mixed_validator.is_valid(value) == (index in (1, 4))
    assert ReplyOutput.model_json_schema() == original
    assert generation_schema([]) == no_facts
