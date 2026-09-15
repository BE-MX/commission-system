import json

from scripts import whatsapp_reply_evaluation as evaluation
from tests.reply_support import output, request, seed_reply
from app.whatsapp_translation.reply_schemas import ReplyOutput


def test_evaluation_covers_thirty_cases_without_printing_generated_body(db, monkeypatch, capsys):
    identity, _, _, _, _, _ = seed_reply(db, monkeypatch)
    calls = []

    def synthetic_call(db, identity, payload):
        calls.append(payload)
        return ReplyOutput(**output(reply_text="SYNTHETIC_PRIVATE_OUTPUT"))

    monkeypatch.setattr(evaluation, "suggest_reply", synthetic_call)
    summary = evaluation.evaluate_cases(db, identity, request)
    printed = capsys.readouterr().out
    assert len(calls) == 30
    assert "SYNTHETIC_PRIVATE_OUTPUT" not in printed
    assert "lightweight" not in printed
    assert json.loads(printed)["semantic_review"] == "pending_business_owner_blind_review"
    assert summary["calls"] == 0


def test_diagnostics_never_echo_model_values(monkeypatch, capsys):
    import pytest
    from app.whatsapp_translation import reply_direct
    from app.whatsapp_translation.errors import WhatsAppTranslationError
    evaluation.install_metadata_diagnostics(monkeypatch)
    with pytest.raises(WhatsAppTranslationError):
        reply_direct._object('SYNTHETIC_PRIVATE_OUTPUT invalid JSON')
    printed = capsys.readouterr().out
    assert "SYNTHETIC_PRIVATE_OUTPUT" not in printed
    assert "invalid_json_object" in printed


def test_commercial_terms_do_not_generate_safety_rejection_diagnostics(monkeypatch, capsys):
    from app.whatsapp_translation import reply_direct
    evaluation.install_metadata_diagnostics(monkeypatch)
    payload = output(reply_text="SYNTHETIC_PRIVATE_OUTPUT: We offer free samples.")
    assert reply_direct._object(json.dumps(payload))["reply_text"] == payload["reply_text"]
    assert capsys.readouterr().out == ""
