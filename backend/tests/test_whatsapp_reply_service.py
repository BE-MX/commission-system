import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.models import ArkPermission, ArkRolePermission, ArkUser
from app.ai.models import AiPreset, AiProvider
from app.core.database import get_db
from app.core.time import beijing_now
from app.knowledge import service as knowledge
from app.knowledge.models import KnowledgeLibraryMember, KnowledgeLibrary, KnowledgeAuditLog
from app.main import app
from app.whatsapp_translation import reply_rewrite, reply_service, reply_state
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import ReplyRequestRecord, TranslationDevice
from tests.reply_support import encode, mock_model, output, plan, request, seed_reply


@pytest.fixture(autouse=True)
def clear_cache():
    reply_state.reply_cache.clear()
    reply_rewrite._cache.clear()
    yield
    reply_state.reply_cache.clear()
    reply_rewrite._cache.clear()


@pytest.fixture
def setup_reply(db, monkeypatch):
    return seed_reply(db, monkeypatch)


def test_direct_call_is_metadata_only_and_response_echoes_snapshot(db, setup_reply, monkeypatch, caplog):
    identity, _, _, _, fact, _ = setup_reply
    calls = mock_model(monkeypatch)
    payload = request()
    result = reply_service.suggest_reply(db, identity, payload)
    assert result.request_id == payload.request_id
    assert result.conversation_epoch == payload.conversation_epoch
    assert result.context_version == payload.context_version and result.draft_version == payload.draft_version
    assert result.sources[1].revision_id == fact["revision_id"]
    assert len(calls) == 1
    assert all(call["snapshot_mode"] == "metadata" for call in calls)
    assert all(call["caller_user_id"] == identity.user_id for call in calls)
    assert 0 < calls[0]["timeout_sec"] <= 120
    row = db.query(ReplyRequestRecord).one()
    persisted = encode({column.name: str(getattr(row, column.name)) for column in row.__table__.columns})
    for forbidden in [payload.messages[0].text, result.reply_text, result.rationale_zh, "Genius Weft"]:
        assert forbidden not in persisted + caplog.text
    assert row.source_revisions[1]["revision_id"] == fact["revision_id"]
    assert "total" in row.timings_ms
    assert not db.query(KnowledgeAuditLog).filter(KnowledgeAuditLog.action.like("%search%")).count()


def test_same_request_reuses_only_authorized_local_result(db, setup_reply, monkeypatch):
    identity = setup_reply[0]
    calls = mock_model(monkeypatch)
    payload = request()
    first = reply_service.suggest_reply(db, identity, payload)
    second = reply_service.suggest_reply(db, identity, payload)
    assert first == second
    assert len(calls) == 1
    assert db.query(ReplyRequestRecord).count() == 1


def test_duplicate_id_with_different_payload_never_calls_again(db, setup_reply, monkeypatch):
    identity = setup_reply[0]
    calls = mock_model(monkeypatch)
    payload = request()
    reply_service.suggest_reply(db, identity, payload)
    with pytest.raises(WhatsAppTranslationError) as caught:
        reply_service.suggest_reply(db, identity, payload.model_copy(update={"goal": "different"}))
    assert caught.value.error_code == "reply_request_conflict"
    assert len(calls) == 1


@pytest.mark.parametrize("state", ["cache_lost", "other_worker", "pending_expired", "failed"])
def test_duplicate_with_unavailable_result_never_restarts_cost(db, setup_reply, monkeypatch, state):
    identity, *_, settings = setup_reply
    payload = request()
    row, owned = reply_state.reserve_request(db, identity, payload, settings)
    assert owned
    row.status = "ready"
    if state == "other_worker":
        row.owner_id = "different-worker"
    if state == "pending_expired":
        row.status = "pending"
        row.lease_until = beijing_now() - timedelta(seconds=1)
    if state == "failed":
        row.status = "failed"
    db.commit()
    calls = mock_model(monkeypatch)
    with pytest.raises(WhatsAppTranslationError) as caught:
        reply_service.suggest_reply(db, identity, payload)
    assert caught.value.error_code in {"reply_result_unavailable", "reply_in_progress"}
    assert calls == []


@pytest.mark.parametrize("change", ["grant", "device", "user", "acl", "library", "revision", "config", "preset"])
@pytest.mark.parametrize("when", ["during", "cached"])
def test_revocation_or_source_change_prevents_return(db, setup_reply, monkeypatch, change, when):
    identity, _, library, policy, _, settings = setup_reply

    def mutate(db, call_number=1):
        if call_number != 1:
            return
        if change == "grant":
            permission = db.query(ArkPermission).filter_by(code="whatsapp_reply:write").one()
            db.query(ArkRolePermission).filter_by(permission_id=permission.id).delete()
        elif change == "device":
            db.query(TranslationDevice).filter_by(id=identity.device_id).update({"is_active": False})
        elif change == "user":
            db.query(ArkUser).filter_by(id=identity.user_id).update({"is_active": False})
        elif change == "acl":
            db.query(KnowledgeLibraryMember).filter_by(library_id=library.id, user_id=identity.user_id).delete()
        elif change == "library":
            db.query(KnowledgeLibrary).filter_by(id=library.id).update({"status": "archived"})
        elif change == "revision":
            actor = {"sub": str(identity.user_id), "roles": ["super_admin"]}
            knowledge.save_document(db, actor, policy["document_id"], title="Changed policy", content={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Internal-only revised condition."}]}]})
            knowledge.approve_request(db, actor, knowledge.submit_document(db, actor, policy["document_id"]).id)
        elif change == "config":
            monkeypatch.setattr(settings, "WHATSAPP_REPLY_SOURCE_BINDINGS", [])
        elif change == "preset":
            db.query(AiPreset).filter_by(preset_name="whatsapp_reply_generator").update({"model": "changed-model"})
        db.commit()

    calls = mock_model(monkeypatch, on_call=mutate if when == "during" else None)
    payload = request()
    if when == "cached":
        reply_service.suggest_reply(db, identity, payload)
        mutate(db)
    with pytest.raises(WhatsAppTranslationError) as caught:
        reply_service.suggest_reply(db, identity, payload)
    assert caught.value.error_code in {"reply_permission_denied", "device_revoked", "reply_sources_changed", "reply_configuration_changed"}
    assert len(calls) == 1


def test_missing_policy_still_provides_editable_draft_with_warning(db, setup_reply, monkeypatch):
    identity, _, library, _, _, _ = setup_reply
    db.query(KnowledgeLibraryMember).filter_by(library_id=library.id).delete()
    db.commit()
    calls = mock_model(monkeypatch)
    result = reply_service.suggest_reply(db, identity, request())
    assert len(calls) == 1
    assert result.sources == [] and result.claims == []
    assert result.status == "ready"
    assert "knowledge_unavailable" in result.risk_flags
    assert result.reply_text == output()["reply_text"]


def test_retrieval_error_is_not_reported_as_no_knowledge(db, setup_reply, monkeypatch):
    calls = mock_model(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE_BODY")

    monkeypatch.setattr(reply_service, "retrieve_reply_sources", fail)
    with pytest.raises(WhatsAppTranslationError) as caught:
        reply_service.suggest_reply(db, setup_reply[0], request())
    assert caught.value.error_code == "reply_unavailable"
    assert len(calls) == 0


def test_invalid_response_is_not_retried_or_cached(db, setup_reply, monkeypatch):
    calls = mock_model(monkeypatch, generator=output(reply_text=""))
    payload = request()
    with pytest.raises(WhatsAppTranslationError):
        reply_service.suggest_reply(db, setup_reply[0], payload)
    with pytest.raises(WhatsAppTranslationError):
        reply_service.suggest_reply(db, setup_reply[0], payload)
    assert len(calls) == 1
    assert db.query(ReplyRequestRecord).one().status == "failed"


def test_concurrency_and_daily_quota_are_independent_of_translation(db, setup_reply, monkeypatch):
    identity, *_, settings = setup_reply
    first, _ = reply_state.reserve_request(db, identity, request(), settings)
    with pytest.raises(WhatsAppTranslationError) as busy:
        reply_state.reserve_request(db, identity, request(), settings)
    assert busy.value.error_code == "reply_busy"
    reply_state.finish_request(db, first.id, status="failed")
    monkeypatch.setattr(settings, "WHATSAPP_REPLY_DAILY_REQUESTS", 1)
    with pytest.raises(WhatsAppTranslationError) as quota:
        reply_state.reserve_request(db, identity, request(), settings)
    assert quota.value.error_code == "reply_daily_quota_exceeded"


def test_invalid_http_body_does_not_echo_private_values(db, setup_reply):
    payload = request().model_dump(mode="json")
    payload["messages"] = [{"role": "intruder", "text": "SYNTHETIC_PRIVATE_BODY"}]
    token = setup_reply[1]
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post("/api/whatsapp-translation/reply-suggestions", json=payload,
                                       headers={"Authorization": f"Bearer {token}", "X-Ark-Extension-Version": "1.2.6"})
        assert response.status_code == 422
        assert response.headers["Cache-Control"] == "no-store"
        assert "SYNTHETIC_PRIVATE_BODY" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_real_http_device_mapping_and_no_store(db, setup_reply, monkeypatch):
    calls = mock_model(monkeypatch)
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post("/api/whatsapp-translation/reply-suggestions", json=request().model_dump(mode="json"),
                                       headers={"Authorization": f"Bearer {setup_reply[1]}", "X-Ark-Extension-Version": "1.2.6"})
        assert response.status_code == 200, response.json()
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["data"]["reply_language"] == "en"
        assert calls[0]["caller_user_id"] == setup_reply[0].user_id
    finally:
        app.dependency_overrides.clear()


def test_chinese_conversation_retrieves_fact_via_bigrams(db, setup_reply, monkeypatch):
    identity, _, _, _, fact, _ = setup_reply
    mock_model(monkeypatch)
    result = reply_service.suggest_reply(db, identity, request(messages=[
        {"role": "customer", "text": "请问你们的发帘接缝厚吗"},
    ]))
    assert any(source.document_id == fact["document_id"] for source in result.sources)


def test_query_terms_capped_with_recency_priority(db, setup_reply, monkeypatch):
    identity = setup_reply[0]
    captured = []
    real_retrieve = reply_service.retrieve_reply_sources

    def observed(*args, **kwargs):
        captured.append(args[3])
        return real_retrieve(*args, **kwargs)

    monkeypatch.setattr(reply_service, "retrieve_reply_sources", observed)
    mock_model(monkeypatch)
    messages = [{"role": "customer", "text": " ".join(f"word{index:03d}" for index in range(batch * 50, batch * 50 + 50))}
                for batch in range(10)]
    messages[-1]["text"] += " zzzrecentmarker"
    reply_service.suggest_reply(db, identity, request(messages=messages))
    assert len(captured) == 1
    assert len(captured[0]) <= 300
    assert "zzzrecentmarker" in captured[0]
    assert "word000" not in captured[0]  # the cap drops the oldest terms first


def _enable_rewrite_preset(db, settings):
    provider = db.query(AiProvider).filter_by(name="synthetic-reply").one()
    db.add(AiPreset(preset_name=settings.WHATSAPP_REPLY_QUERY_REWRITE_PRESET, provider_id=provider.id,
                    model="synthetic-model", is_enabled=True, parameters={"max_tokens": 400}))
    db.commit()


def test_query_rewrite_recovers_lexical_miss(db, setup_reply, monkeypatch):
    identity, _, _, _, fact, settings = setup_reply
    _enable_rewrite_preset(db, settings)
    calls = []

    def fake_chat(db, **kwargs):
        calls.append(kwargs)
        if kwargs["preset_name"] == settings.WHATSAPP_REPLY_QUERY_REWRITE_PRESET:
            return {"content": encode({"queries": ["thin seam"]}), "log_id": len(calls)}
        return {"content": encode({**output(), "memory_changes": []}), "log_id": len(calls)}

    monkeypatch.setattr(reply_service, "chat", fake_chat)
    result = reply_service.suggest_reply(db, identity, request(messages=[
        {"role": "customer", "text": "Quelle est la couture?"},
    ]))
    assert any(call["preset_name"] == settings.WHATSAPP_REPLY_QUERY_REWRITE_PRESET for call in calls)
    assert any(source.document_id == fact["document_id"] for source in result.sources)
    assert "no_public_facts" not in result.risk_flags


def test_query_rewrite_not_attempted_when_lexical_retrieval_succeeds(db, setup_reply, monkeypatch):
    identity, _, _, _, fact, settings = setup_reply
    _enable_rewrite_preset(db, settings)
    calls = mock_model(monkeypatch)
    result = reply_service.suggest_reply(db, identity, request())
    assert any(source.document_id == fact["document_id"] for source in result.sources)
    assert len(calls) == 1


def test_query_rewrite_failure_falls_back_to_lexical_draft(db, setup_reply, monkeypatch):
    identity, *_, settings = setup_reply
    _enable_rewrite_preset(db, settings)
    calls = []

    def fake_chat(db, **kwargs):
        calls.append(kwargs)
        if kwargs["preset_name"] == settings.WHATSAPP_REPLY_QUERY_REWRITE_PRESET:
            raise TimeoutError("synthetic timeout")
        return {"content": encode({**output(), "memory_changes": []}), "log_id": len(calls)}

    monkeypatch.setattr(reply_service, "chat", fake_chat)
    result = reply_service.suggest_reply(db, identity, request(messages=[
        {"role": "customer", "text": "Quelle est la couture?"},
    ]))
    assert len(calls) == 2
    assert result.status == "ready"
    assert "no_public_facts" in result.risk_flags


def test_stale_binding_adds_risk_flag_without_failing_draft(db, setup_reply, monkeypatch):
    identity, *_, settings = setup_reply
    bindings = [dict(item) for item in settings.WHATSAPP_REPLY_SOURCE_BINDINGS]
    bindings[1]["content_hash"] = "0" * 64
    monkeypatch.setattr(settings, "WHATSAPP_REPLY_SOURCE_BINDINGS", bindings)
    mock_model(monkeypatch)
    result = reply_service.suggest_reply(db, identity, request())
    assert result.status == "ready"
    assert "knowledge_binding_stale" in result.risk_flags


def test_detected_language_drives_glossary_over_fallback(db, setup_reply, monkeypatch):
    identity = setup_reply[0]
    captured = {}
    real_glossary = reply_service.glossary_for

    def observed(db, **kwargs):
        captured.update(kwargs)
        return real_glossary(db, **kwargs)

    monkeypatch.setattr(reply_service, "glossary_for", observed)
    mock_model(monkeypatch)
    reply_service.suggest_reply(db, identity, request(detected_language="fr"))
    assert captured["target_language"] == "fr"
    reply_service.suggest_reply(db, identity, request(target_language="es"))
    assert captured["target_language"] == "es"
    reply_service.suggest_reply(db, identity, request())
    assert captured["target_language"] == "en"


def test_detected_language_must_be_a_supported_code(db, setup_reply):
    with pytest.raises(ValueError):
        request(detected_language="xx")
    assert request(detected_language="").detected_language == ""


def test_handoff_next_step_uses_first_missing_information(db, setup_reply, monkeypatch):
    identity = setup_reply[0]
    mock_model(monkeypatch, generator=output(missing_information=["需确认是否可定制颜色"]))
    result = reply_service.suggest_reply(db, identity, request())
    assert result.action.focus == "需确认是否可定制颜色"
    assert result.handoff["next_step"] == "需确认是否可定制颜色"


def test_auto_handoff_next_step_uses_real_review_reason(db, setup_reply, monkeypatch):
    identity = setup_reply[0]
    mock_model(monkeypatch, generator=output(auto_action="reply", reply_segments="not-a-list"))
    result = reply_service.suggest_reply(db, identity, request(mode="auto"))
    assert result.auto_action == "handoff"
    assert result.action.kind == "handoff"
    assert result.action.focus == "模型分段格式不完整，已保留回复，请人工处理。"
    assert result.handoff["next_step"] == result.action.focus
