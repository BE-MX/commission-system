"""Synthetic multi-turn regression, isolated SQLite only."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import time as core_time
from app.core.database import get_db
from app.main import app
from app.whatsapp_translation import reply_memory, reply_service, reply_state
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import ReplyInquiry, TranslationDevice
from app.whatsapp_translation.reply_memory_schemas import MemoryCommand
from app.whatsapp_translation.reply_schemas import ReplyPlan
from tests.reply_support import mock_model, output, plan, request, seed_reply


@pytest.fixture(autouse=True)
def clear_cache():
    reply_state.reply_cache.clear()
    yield
    reply_state.reply_cache.clear()


def command(db, identity, operation, **values):
    return reply_memory.handle_memory(db, identity, MemoryCommand(operation=operation, **values))


def create(db, identity, **kwargs):
    return command(db, identity, "create", conversation_id=uuid4(), **kwargs)["inquiry"]


def change(**values):
    return {"kind": "need", "status": "tentative", "summary": "20 units initially", "message_index": 0, "quote": "20 units", **values}


def generate(db, identity, monkeypatch, inquiry, *, changes=None, text="I would like 20 units.", **kwargs):
    mock_model(monkeypatch, planner=plan(memory_changes=changes if changes is not None else [change()]),
               generator=output(reply_text="Understood, 20 units as a starting quantity.", claims=[]))
    payload = request(messages=[{"role": "customer", "text": text}], memory_conversation_id=inquiry["id"], memory_revision=inquiry["revision"], **kwargs)
    return reply_service.suggest_reply(db, identity, payload), payload


def commit(db, identity, response):
    return command(db, identity, "commit", conversation_id=response.memory_conversation_id,
                   revision=response.memory_revision, request_id=response.request_id)["inquiry"]


def test_generation_proposes_only_and_commit_is_idempotent(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    response, _ = generate(db, identity, monkeypatch, inquiry, draft_intent="I already sent the catalog.")
    assert db.get(ReplyInquiry, inquiry["id"]).entries == []
    assert len(response.memory_update) == 1
    first = commit(db, identity, response)
    second = commit(db, identity, response)
    assert first == second and first["revision"] == 1
    assert first["entries"][0]["status"] == "tentative"
    assert "catalog" not in str(first)


def test_latest_correction_supersedes_prior_customer_need_with_evidence(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    first, _ = generate(db, identity, monkeypatch, inquiry)
    saved = commit(db, identity, first)
    entry = saved["entries"][0]
    payload = request(messages=[{"role": "customer", "text": "Change the quantity to 10 units."}],
                      memory_conversation_id=inquiry["id"], memory_revision=1)
    calls = mock_model(monkeypatch, planner=plan(memory_changes=[change(replaces=entry["id"], summary="10 units initially", quote="10 units")]),
                       generator=output(reply_text="Understood, 10 units as a starting quantity.", claims=[]))
    second = reply_service.suggest_reply(db, identity, payload)
    latest = commit(db, identity, second)
    assert latest["revision"] == 2 and len(latest["entries"]) == 1
    assert latest["entries"][0]["summary"] == "10 units initially"
    assert [e["quote"] for e in latest["entries"][0]["evidence"]] == ["20 units", "10 units"]
    assert "saved_observations" in calls[0]["messages"][1]["content"]


@pytest.mark.parametrize("operation", ["read", "delete", "commit", "correct", "create"])
def test_device_and_user_ownership_cannot_be_overridden(db, monkeypatch, operation):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    # Real live user/device, with a foreign record assigned to a different scope.
    row = db.get(ReplyInquiry, inquiry["id"])
    row.device_id = identity.device_id + 100
    db.commit()
    values = {"conversation_id": inquiry["id"], "revision": 0}
    if operation == "commit": values["request_id"] = uuid4()
    if operation == "correct": values.update(entry_id=uuid4(), status="cancelled", note="wrong inquiry")
    with pytest.raises(WhatsAppTranslationError) as caught:
        command(db, identity, operation, **values)
    assert caught.value.error_code == "reply_memory_not_found"
    assert command(db, identity, "list")["inquiries"] == []


def test_foreign_owner_hidden_even_when_same_device_id(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    row = db.get(ReplyInquiry, inquiry["id"]); row.user_id += 100; db.commit()
    with pytest.raises(WhatsAppTranslationError, match="completed"):
        command(db, identity, "read", conversation_id=inquiry["id"])
    assert not command(db, identity, "list")["inquiries"]


def test_manual_correction_prevents_pending_candidate_overwrite(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    response, _ = generate(db, identity, monkeypatch, inquiry)
    saved = commit(db, identity, response)
    candidate, _ = generate(db, identity, monkeypatch, saved, changes=[])
    corrected = command(db, identity, "correct", conversation_id=inquiry["id"], revision=1,
                        entry_id=saved["entries"][0]["id"], status="human_confirmed", note="Customer confirmed the initial quantity.")["inquiry"]
    with pytest.raises(WhatsAppTranslationError) as caught:
        commit(db, identity, candidate)
    assert caught.value.error_code == "reply_memory_conflict"
    assert command(db, identity, "read", conversation_id=inquiry["id"])["inquiry"] == corrected


def test_deleted_inquiry_cannot_be_resurrected_by_cached_result(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    response, _ = generate(db, identity, monkeypatch, inquiry)
    command(db, identity, "delete", conversation_id=inquiry["id"], revision=0)
    with pytest.raises(WhatsAppTranslationError) as caught:
        commit(db, identity, response)
    assert caught.value.error_code == "reply_memory_not_found"
    assert db.query(ReplyInquiry).count() == 0


def test_commit_without_cached_candidate_never_repeats_model_call(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    response, _ = generate(db, identity, monkeypatch, inquiry)
    reply_state.reply_cache.clear()
    monkeypatch.setattr(reply_service, "chat", lambda *a, **k: pytest.fail("must not regenerate"))
    with pytest.raises(WhatsAppTranslationError) as caught:
        commit(db, identity, response)
    assert caught.value.error_code == "reply_result_unavailable"


@pytest.mark.parametrize("bad", [
    change(quote="I already sent the catalog."), change(message_index=1),
    change(kind="commitment", status="reported_done"), change(replaces=str(uuid4())),
])
def test_model_cannot_use_draft_fabricated_quote_role_or_foreign_entry(bad):
    payload = request(messages=[{"role": "customer", "text": "20 units"}], draft_intent="I already sent the catalog.")
    with pytest.raises(WhatsAppTranslationError) as caught:
        reply_memory.build_update(ReplyPlan.model_validate(plan(memory_changes=[bad])), payload, [])
    assert caught.value.error_code == "reply_invalid_evidence"


def test_seller_reported_completion_is_not_tool_or_human_completion():
    payload = request(messages=[{"role": "salesperson", "text": "I have sent the catalog."}])
    p = ReplyPlan.model_validate(plan(memory_changes=[change(kind="commitment", status="reported_done", quote="sent the catalog", summary="Seller reports catalog sent")]))
    entries = reply_memory.build_update(p, payload, [])
    assert entries[0]["status"] == "reported_done"
    assert reply_memory.handoff_summary(entries, p)["commitments"][0]["status"] == "reported_done"


def test_masking_and_no_client_control_over_candidate_body(db, monkeypatch):
    identity, _, _, _, _, _ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity, label="sample contact +12345678901")
    assert "+12345678901" not in inquiry["label"]
    with pytest.raises(ValueError):
        MemoryCommand(operation="commit", conversation_id=inquiry["id"], request_id=uuid4(), entries=[{"summary": "invented"}])


@pytest.mark.parametrize("utc_instant,expected", [
    (datetime(2026, 9, 8, 15, 59, 59, tzinfo=timezone.utc), "2026-09-08T23:59:59"),
    (datetime(2026, 9, 8, 16, 0, 0, tzinfo=timezone.utc), "2026-09-09T00:00:00"),
])
def test_retention_uses_beijing_boundary_not_host_time(db, monkeypatch, utc_instant, expected):
    identity, *_ = seed_reply(db, monkeypatch)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            # Simulates a server in a non-Beijing timezone.
            return utc_instant.astimezone(tz or timezone(timedelta(hours=-7)))
    monkeypatch.setattr(core_time, "datetime", Clock)
    inquiry = create(db, identity)
    assert inquiry["created_at"] == expected
    assert datetime.fromisoformat(inquiry["expires_at"]) - datetime.fromisoformat(expected) == timedelta(days=30)
    monkeypatch.setattr(reply_memory, "beijing_now", lambda: datetime.fromisoformat(inquiry["expires_at"]))
    assert command(db, identity, "list")["inquiries"] == []
    assert reply_memory.purge_expired_inquiries(db) == 1


def test_live_device_revocation_blocks_memory_access(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    db.get(TranslationDevice, identity.device_id).is_active = False; db.commit()
    with pytest.raises(WhatsAppTranslationError) as caught:
        command(db, identity, "read", conversation_id=inquiry["id"])
    assert caught.value.error_code == "device_revoked"


def test_memory_http_validation_does_not_echo_private_note(db, monkeypatch):
    _, token, *_ = seed_reply(db, monkeypatch)
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post("/api/whatsapp-translation/reply-memory", headers={"Authorization": f"Bearer {token}", "X-Ark-Extension-Version": "1.3.0"},
                                        json={"operation": "correct", "note": "synthetic-private-note", "conversation_id": "invalid"})
        assert response.status_code == 422
        assert "synthetic-private-note" not in response.text
        assert response.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


def test_recreated_id_rejects_candidate_from_deleted_incarnation(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    response, _ = generate(db, identity, monkeypatch, inquiry)
    command(db, identity, "delete", conversation_id=inquiry["id"], revision=0)
    command(db, identity, "create", conversation_id=inquiry["id"])
    with pytest.raises(WhatsAppTranslationError) as caught:
        commit(db, identity, response)
    assert caught.value.error_code == "reply_memory_conflict"
    assert db.get(ReplyInquiry, inquiry["id"]).entries == []


def test_handoff_uses_human_value_and_reopened_requests():
    base = {"evidence": [], "human_note": "", "summary": "Send catalog", "kind": "request", "status": "pending"}
    entries = [base, {**base, "kind": "need", "status": "human_confirmed", "summary": "20 units", "human_note": "10 units"}]
    handoff = reply_memory.handoff_summary(entries, ReplyPlan.model_validate(plan()))
    assert handoff["needs"] == ["10 units"]
    assert handoff["open_requests"] == ["Send catalog"]


def test_recreated_instance_between_validation_and_atomic_write_is_rejected(db, monkeypatch):
    identity, *_ = seed_reply(db, monkeypatch)
    inquiry = create(db, identity)
    response, _ = generate(db, identity, monkeypatch, inquiry)
    original_write = reply_memory._write
    replacement_instance = str(uuid4())

    def replace_before_update(db, identity, inquiry_id, instance_id, revision, values):
        # Simulate another committed delete/create after validation, before CAS.
        db.query(ReplyInquiry).filter_by(id=inquiry_id).update(
            {"instance_id": replacement_instance, "entries": [], "revision": revision}, synchronize_session=False)
        db.commit()
        return original_write(db, identity, inquiry_id, instance_id, revision, values)

    monkeypatch.setattr(reply_memory, "_write", replace_before_update)
    with pytest.raises(WhatsAppTranslationError) as caught:
        commit(db, identity, response)
    assert caught.value.error_code == "reply_memory_conflict"
    db.expire_all()
    replacement = db.get(ReplyInquiry, inquiry["id"])
    assert replacement.instance_id == replacement_instance
    assert replacement.entries == [] and replacement.revision == 0
