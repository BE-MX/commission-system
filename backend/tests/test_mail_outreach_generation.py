"""generation_service 生成/校验/幂等用例 + schedule_client 侧车降级用例（均无外部调用，走 monkeypatch）。"""

import json
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.mail_outreach import policies, schedule_client
from app.mail_outreach.approval_service import approve
from app.mail_outreach.errors import MailOutreachError
from app.mail_outreach.generation_service import generate_draft
from app.mail_outreach.models import MailOutreachMessage
from app.mail_outreach.schemas import ApproveRequest
from tests.mail_outreach_helpers import make_mailbox, seed_graph


def _fake_chat(payload):
    def fake(db, preset_name, messages, caller_module, caller_user_id=None, **kwargs):
        assert preset_name == "mail_outreach_generate"
        assert kwargs.get("snapshot_mode") == "metadata"
        return {"content": json.dumps(payload, ensure_ascii=False), "log_id": 1}
    return fake


def _generate(db, graph, request_key="req-key-0001"):
    return generate_draft(
        db, graph.access, {"sub": str(graph.user.id)},
        customer_id=graph.customer.id, contact_id=graph.contact.id,
        contact_point_id=graph.point.id, relationship_goal="first_intro",
        request_key=request_key,
    )


def _valid_ai_payload(graph, **overrides):
    payload = {
        "ready": True,
        "missing_requirements": [],
        "subject": "Hair products for Acme",
        "body_text": "Hi Jane, we noticed Acme works in hair products.",
        "language": "en",
        "meaning_summary": "提到客户从事发制品行业。",
        "angle": "行业切入",
        "cta": "回复约通话",
        "claims": [{
            "claim": "Acme 从事发制品行业",
            "fact_id": graph.fact.id,
            "knowledge_version_id": None,
            "allowed_wording": "works in hair products",
        }],
        "risk_flags": [],
    }
    payload.update(overrides)
    return payload


def test_generate_draft_persists_with_valid_claims(db, monkeypatch):
    graph = seed_graph(db)
    monkeypatch.setattr(
        "app.mail_outreach.generation_service.chat",
        _fake_chat(_valid_ai_payload(graph)),
    )
    result = _generate(db, graph)

    revision = result["current_revision"]
    assert result["status"] == "draft"
    assert result["idempotent_replay"] is False
    assert revision["subject"] == "Hair products for Acme"
    assert revision["claims"][0]["fact_id"] == graph.fact.id
    assert revision["risk_flags"] == []
    assert revision["content_sha256"] == policies.compute_content_sha256(
        subject="Hair products for Acme",
        body_text="Hi Jane, we noticed Acme works in hair products.",
        language_tag="en", claims=revision["claims"],
    )
    snapshot = revision["evidence_snapshot"]
    assert snapshot["profile_version_id"] == graph.profile.id
    assert snapshot["contact_point_id"] == graph.point.id
    assert snapshot["email"] == "jane@acme.com"
    assert snapshot["fact_fingerprints"] == [{
        "fact_id": graph.fact.id, "fact_fingerprint": graph.fact.fact_fingerprint,
    }]
    assert snapshot["request_key"] == "req-key-0001"


def test_claim_with_unknown_fact_id_is_dropped(db, monkeypatch):
    graph = seed_graph(db)
    payload = _valid_ai_payload(graph, claims=[
        {"claim": "快照外证据", "fact_id": 424242,
         "knowledge_version_id": None, "allowed_wording": "x"},
    ])
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", _fake_chat(payload))
    result = _generate(db, graph)

    revision = result["current_revision"]
    assert revision["claims"] == []
    codes = [flag["code"] for flag in revision["risk_flags"]]
    assert "claim_evidence_dropped" in codes


def test_ready_false_persists_but_cannot_be_approved(db, monkeypatch):
    graph = seed_graph(db)
    mailbox = make_mailbox(db, owner_user_id=graph.user.id)
    payload = _valid_ai_payload(
        graph, ready=False, missing_requirements=["缺少语言依据"],
    )
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", _fake_chat(payload))
    result = _generate(db, graph)
    revision = result["current_revision"]

    # 正常落库、保持 draft
    assert result["status"] == "draft"
    assert "generation_not_ready" in [f["code"] for f in revision["risk_flags"]]

    with pytest.raises(MailOutreachError) as exc_info:
        approve(db, graph.access, {"sub": str(graph.user.id)}, result["id"], ApproveRequest(
            revision_id=revision["id"], mailbox_binding_id=mailbox.id,
            expected_content_sha256=revision["content_sha256"],
            schedule_policy={}, scheduled_at_utc="2026-09-20T01:00:00+00:00",
            reason="",
        ))
    assert exc_info.value.error_code == "risk_blocked"


def test_empty_not_ready_response_explains_missing_evidence(db, monkeypatch):
    graph = seed_graph(db)
    payload = _valid_ai_payload(
        graph, ready=False, subject="", body_text="",
        missing_requirements=["联系人角色缺少依据"],
    )
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", _fake_chat(payload))
    with pytest.raises(MailOutreachError) as error:
        _generate(db, graph)
    assert error.value.error_code == "generation_not_ready"
    assert "联系人角色缺少依据" in error.value.message
    assert db.query(MailOutreachMessage).count() == 0


@pytest.mark.parametrize("allowed,roles", [("*", ["super_admin"]), ("", ["super_admin"]), ("jane@acme.com", [])])
def test_internal_test_requires_admin_and_explicit_address(db, monkeypatch, allowed, roles):
    graph = seed_graph(db)
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_ALLOWED_RECIPIENTS", allowed)
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", lambda *a, **kw: pytest.fail("must reject before AI"))
    with pytest.raises(MailOutreachError):
        generate_draft(db, graph.access, {"sub": str(graph.user.id), "roles": roles},
            customer_id=graph.customer.id, contact_id=graph.contact.id, contact_point_id=graph.point.id,
            relationship_goal="first_intro", request_key="internal-test-01", internal_test=True)
    assert db.query(MailOutreachMessage).count() == 0


def test_internal_test_uses_separate_prompt_and_preserves_mode_on_edit(db, monkeypatch):
    from app.mail_outreach.generation_service import create_human_revision
    graph = seed_graph(db)
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_ALLOWED_RECIPIENTS", "jane@acme.com")
    user = {"sub": str(graph.user.id), "roles": ["super_admin"]}
    def test_chat(db, **kwargs):
        assert kwargs["preset_name"] == "mail_outreach_internal_test"
        prompt = json.loads(kwargs["messages"][0]["content"])
        assert set(prompt) == {"recipient_name", "language", "purpose"}
        return {"content": json.dumps(_valid_ai_payload(graph, subject="[ARK INTERNAL TEST] Mail check", claims=[]))}
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", test_chat)
    result = generate_draft(db, graph.access, user,
        customer_id=graph.customer.id, contact_id=graph.contact.id, contact_point_id=graph.point.id,
        relationship_goal="first_intro", request_key="internal-test-01", internal_test=True)
    assert result["current_revision"]["evidence_snapshot"]["internal_test"] is True
    assert result["current_revision"]["preset_name"] == "mail_outreach_internal_test"
    assert result["current_revision"]["risk_flags"] == []
    edited = create_human_revision(db, graph.access, user, result["id"], {"body_text": "Please reply to this internal test."})
    assert edited["current_revision"]["evidence_snapshot"]["internal_test"] is True
    regenerated = create_human_revision(db, graph.access, user, result["id"], {"regenerate": True})
    assert regenerated["current_revision"]["preset_name"] == "mail_outreach_internal_test"
    with pytest.raises(MailOutreachError, match="测试主题"):
        create_human_revision(db, graph.access, user, result["id"], {"subject": "Real outreach"})


def test_request_key_replay_returns_existing_message(db, monkeypatch):
    graph = seed_graph(db)
    calls = {"count": 0}

    def counting_chat(db, preset_name, messages, caller_module, caller_user_id=None, **kw):
        calls["count"] += 1
        return _fake_chat(_valid_ai_payload(graph))(
            db, preset_name, messages, caller_module, caller_user_id, **kw,
        )

    monkeypatch.setattr("app.mail_outreach.generation_service.chat", counting_chat)
    first = _generate(db, graph)
    second = _generate(db, graph)

    assert calls["count"] == 1
    assert second["id"] == first["id"]
    assert second["idempotent_replay"] is True
    assert db.query(MailOutreachMessage).count() == 1


def test_commercial_promise_keyword_flagged(db, monkeypatch):
    graph = seed_graph(db)
    payload = _valid_ai_payload(
        graph, body_text="We can offer 20% discount and low MOQ.",
    )
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", _fake_chat(payload))
    result = _generate(db, graph)
    codes = [f["code"] for f in result["current_revision"]["risk_flags"]]
    assert "unapproved_commercial_promise" in codes


def test_ineligible_rejected_without_empty_draft_or_ai(db, monkeypatch):
    """资格不合格：不调 AI，落空内容草稿并把缺项记入 risk_flags。"""
    graph = seed_graph(db, verification_status="unknown")

    def forbidden_chat(*args, **kwargs):
        raise AssertionError("不合格时不应调用 AI")

    monkeypatch.setattr("app.mail_outreach.generation_service.chat", forbidden_chat)
    with pytest.raises(MailOutreachError) as error:
        _generate(db, graph)
    assert error.value.error_code == "eligibility_missing"
    assert db.query(MailOutreachMessage).count() == 0


# ── schedule_client：侧车降级与透传（mock HTTP 层） ─────────────────


def test_schedule_preview_unavailable_when_url_blank(db, monkeypatch):
    monkeypatch.setattr(
        get_settings(), "MAIL_OUTREACH_SCHEDULE_SERVICE_URL", "",
    )
    with pytest.raises(MailOutreachError) as exc_info:
        schedule_client.preview_schedule({"country": "US"})
    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "schedule_service_unavailable"


def test_schedule_preview_passes_through_ok_payload(db, monkeypatch):
    monkeypatch.setattr(
        get_settings(), "MAIL_OUTREACH_SCHEDULE_SERVICE_URL",
        "http://127.0.0.1:3999", raising=False,
    )
    monkeypatch.setattr(
        get_settings(), "MAIL_OUTREACH_SCHEDULE_TOKEN", "tok", raising=False,
    )
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"ok": True, "scheduled_at_utc": "2026-09-21T01:05:00Z"},
            text="ok",
        )

    monkeypatch.setattr("app.mail_outreach.schedule_client.httpx.post", fake_post)
    data = schedule_client.preview_schedule({"country": "US", "timezone": "America/New_York"})
    assert data["ok"] is True
    assert data["scheduled_at_utc"] == "2026-09-21T01:05:00Z"
    assert seen["url"] == "http://127.0.0.1:3999/schedule/preview"
    assert seen["headers"]["Authorization"] == "Bearer tok"


def test_schedule_preview_sidecar_rejection_surfaces_message(db, monkeypatch):
    monkeypatch.setattr(
        get_settings(), "MAIL_OUTREACH_SCHEDULE_SERVICE_URL",
        "http://127.0.0.1:3999", raising=False,
    )

    def fake_post(url, json=None, headers=None, timeout=None):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"ok": False, "message": "多语国家缺少语言依据"},
            text="",
        )

    monkeypatch.setattr("app.mail_outreach.schedule_client.httpx.post", fake_post)
    with pytest.raises(MailOutreachError) as exc_info:
        schedule_client.preview_schedule({"country": "NG"})
    assert exc_info.value.error_code == "schedule_preview_rejected"
    assert "多语国家缺少语言依据" in exc_info.value.message


def test_unknown_knowledge_and_edit_cannot_clear_evidence_risk(db, monkeypatch):
    from app.mail_outreach.generation_service import create_human_revision, BLOCKING_RISK_CODES
    graph = seed_graph(db)
    payload = _valid_ai_payload(graph, claims=[{"claim": "invented", "knowledge_version_id": 9999}])
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", _fake_chat(payload))
    result = _generate(db, graph)
    revision = result["current_revision"]
    assert revision["claims"] == []
    assert "claim_evidence_dropped" in [f["code"] for f in revision["risk_flags"]]
    assert "claim_evidence_dropped" in BLOCKING_RISK_CODES
    edited = create_human_revision(db, graph.access, {"sub": str(graph.user.id)}, result["id"], {"subject": "Updated"})
    assert "claim_evidence_dropped" in [f["code"] for f in edited["current_revision"]["risk_flags"]]


def test_completed_message_cannot_be_edited(db):
    from app.mail_outreach.generation_service import create_human_revision
    from tests.mail_outreach_helpers import make_draft
    graph = seed_graph(db)
    message, _revision = make_draft(db, graph)
    message.status = "completed"
    db.flush()
    with pytest.raises(MailOutreachError) as error:
        create_human_revision(db, graph.access, {"sub": str(graph.user.id)}, message.id, {"subject": "Changed"})
    assert error.value.error_code == "message_not_editable"


def test_schedule_client_translates_actual_sidecar_contract(monkeypatch):
    monkeypatch.setattr(get_settings(), "MAIL_OUTREACH_SCHEDULE_SERVICE_URL", "http://localhost:3999")
    def fake_post(url, json, **kwargs):
        assert json == {"country": "US", "state": "NY", "languageSource": "recipient", "languageBasis": "confirmed", "officeStart": "09:00"}
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "data": {"state": "NY", "scheduledAtUtc": "2026-09-21T13:05:00Z", "scheduledAtLocal": "2026-09-21T09:05:00-04:00", "officeStart": "09:00", "localDate": "2026-09-21"}})
    monkeypatch.setattr(schedule_client.httpx, "post", fake_post)
    result = schedule_client.preview_schedule({"country": "US", "state": "NY", "language_source": "recipient", "language_basis": "confirmed", "office_start": "09:00"})
    assert result["scheduled_at_utc"] == "2026-09-21T13:05:00Z"
    assert result["state"] == "NY"
    assert result["office_start"] == "09:00"
    assert "data" not in result


def test_ai_failure_does_not_leave_empty_committed_message(db, monkeypatch):
    graph = seed_graph(db)
    def fake_chat(db, **kwargs):
        # Real facade commits its log before making the external call.
        db.commit()
        raise ValueError("provider unavailable")
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", fake_chat)
    with pytest.raises(ValueError):
        _generate(db, graph)
    db.rollback()
    assert db.query(MailOutreachMessage).count() == 0


def test_regeneration_rechecks_state_after_ai_facade_commit(db, monkeypatch):
    from app.mail_outreach.generation_service import create_human_revision
    from tests.mail_outreach_helpers import make_draft
    graph = seed_graph(db)
    message, _ = make_draft(db, graph)
    def fake_chat(db, **kwargs):
        message.status = "completed"
        db.commit()
        return {"content": json.dumps(_valid_ai_payload(graph))}
    monkeypatch.setattr("app.mail_outreach.generation_service.chat", fake_chat)
    with pytest.raises(MailOutreachError) as error:
        create_human_revision(db, graph.access, {"sub": str(graph.user.id)}, message.id, {"regenerate": True})
    assert error.value.error_code == "message_not_editable"
