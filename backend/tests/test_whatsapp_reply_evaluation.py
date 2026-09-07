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
    from app.whatsapp_translation import reply_guard
    from app.whatsapp_translation.reply_schemas import ReplyPlan
    from app.whatsapp_translation.errors import WhatsAppTranslationError
    evaluation.install_metadata_diagnostics(monkeypatch)
    with pytest.raises(WhatsAppTranslationError):
        reply_guard.parse_json('{"stage":"SYNTHETIC_PRIVATE_OUTPUT"}', ReplyPlan)
    printed = capsys.readouterr().out
    assert "SYNTHETIC_PRIVATE_OUTPUT" not in printed
    assert "missing" in printed
    assert "schema_validation" in printed


def test_safety_diagnostic_classifies_rule_without_echoing_draft(monkeypatch, capsys):
    import pytest
    from app.whatsapp_translation import reply_service
    from app.whatsapp_translation.errors import WhatsAppTranslationError
    evaluation.install_metadata_diagnostics(monkeypatch)
    payload = output(reply_text="SYNTHETIC_PRIVATE_OUTPUT: We offer free samples.", claims=[])
    with pytest.raises(WhatsAppTranslationError):
        reply_service.validate_output(json.dumps(payload), "en", [], request())
    printed = capsys.readouterr().out
    assert "commercial_or_internal_term" in printed
    assert "free samples" not in printed
    assert "SYNTHETIC_PRIVATE_OUTPUT" not in printed
