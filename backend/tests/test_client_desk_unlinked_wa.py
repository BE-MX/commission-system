"""B track, WhatsApp channel: admission gate, scan, analysis, revocation and link actions on isolated SQLite.

Owner authorisation and the model are faked; the WhatsApp body/enrolment rules themselves
are covered by the WhatsApp and client-desk suites. Nothing here calls a real provider.
"""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.client_desk import link_service, private_scope
from app.client_desk.models import (
    ClientDeskState,
    ClientDeskUnlinkedReview,
    ClientDeskUnlinkedRun,
    ClientDeskUnlinkedThread,
    ClientDeskWaLink,
)
from app.client_desk.unlinked import service, wa, worker
from app.core.time import beijing_now
from app.whatsapp import lifecycle
from app.whatsapp.models import (
    WhatsAppAccount, WhatsAppAuditLog, WhatsAppBodyGrant, WhatsAppConversation, WhatsAppMessage,
)

TABLES = [
    ClientDeskUnlinkedThread, ClientDeskUnlinkedRun, ClientDeskUnlinkedReview, ClientDeskWaLink,
    ClientDeskState, WhatsAppAccount, WhatsAppConversation, WhatsAppMessage, WhatsAppAuditLog, WhatsAppBodyGrant,
]
USER = {"sub": "1"}
GOOD = {
    "is_business_lead": True, "intent_stage": "quoting", "urgency": "high",
    "one_line_summary": "问 22 寸 #613 现货", "missing_or_next_action": "确认库存后回复",
    "breakthrough_angle": "更在意交期", "draft_message": "Hi, we have [库存] in stock.",
    "extracted_clues": {"company": "Hair Lab"}, "cites": ["M-1"],
}


def _settings(**over):
    base = dict(
        CLIENT_DESK_UNLINKED_ENABLED=True, CLIENT_DESK_UNLINKED_TM_ENABLED=False,
        CLIENT_DESK_UNLINKED_WA_ENABLED=True, CLIENT_DESK_UNLINKED_PRESET_NAME="client_desk_unlinked",
        CLIENT_DESK_UNLINKED_DAILY_QUOTA=20, CLIENT_DESK_UNLINKED_WEEKLY_REPORT_ENABLED=True,
        CLIENT_DESK_ALLOWED_PROVIDER_IDS=[7],
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'wa_unlinked.db'}")
    for model in TABLES:
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    cfg = _settings()
    monkeypatch.setattr(wa, "get_settings", lambda: cfg)
    monkeypatch.setattr(worker, "get_settings", lambda: cfg)
    monkeypatch.setattr(wa, "owner_allowed", lambda db, account, action="read": True)
    monkeypatch.setattr(private_scope, "list_private_companies", lambda db, user, **kw: [])
    monkeypatch.setattr(link_service, "require_enabled", lambda *a, **kw: None)
    monkeypatch.setattr(link_service, "require_account", lambda *a, **kw: None)
    monkeypatch.setattr(link_service, "assert_company_access", lambda db, user, company_id: None)
    monkeypatch.setattr(wa, "prepare_text_chat", lambda *a, **kw: SimpleNamespace(
        provider=SimpleNamespace(id=7), preset=SimpleNamespace(system_prompt=None)))
    calls = []

    def fake_chat(db, **kwargs):
        calls.append(kwargs)
        return {"content": json.dumps(GOOD), "finish_reason": "stop", "tokens_prompt": 9, "tokens_completion": 4}

    monkeypatch.setattr(wa, "chat", fake_chat)
    with factory() as db:
        _seed(db)
    yield SimpleNamespace(factory=factory, cfg=cfg, calls=calls, monkeypatch=monkeypatch)
    engine.dispose()


def _account(db, uid, owner, **over):
    data = dict(account_uid=uid, ark_user_id=owner, provider="baileys", status="active",
                consent_state="active", crm_shared=True, ai_egress_allowed=True, unlinked_ai_allowed=True,
                consent_version=2, session_generation=3, phone_number=None)
    data.update(over)
    db.add(WhatsAppAccount(**data))


def _chat(db, account_uid, conv_uid, *, phone="447700900123", name="Maria", group=False, minutes=30,
          direction="in", text="Hi, do you have 22 inch #613 in stock?"):
    db.add(WhatsAppConversation(account_uid=account_uid, conversation_uid=conv_uid, chat_id=f"{phone}@s.whatsapp.net",
                                contact_phone=phone, contact_name=name, is_group=group))
    db.add(WhatsAppMessage(account_uid=account_uid, conversation_uid=conv_uid, message_uid=f"m-{conv_uid}",
                           external_message_id=f"e-{conv_uid}", direction=direction, content_text=text,
                           sent_at=beijing_now() - timedelta(minutes=minutes)))


def _seed(db):
    _account(db, "acc-1", 1)
    _account(db, "acc-colleague", 2, phone_number="+86 138 0000 1111", unlinked_ai_allowed=False)
    _account(db, "acc-off", 3, unlinked_ai_allowed=False)
    _chat(db, "acc-1", "lead")
    _chat(db, "acc-1", "group", phone="447700900124", group=True)
    _chat(db, "acc-1", "colleague", phone="8613800001111")
    _chat(db, "acc-1", "linked", phone="447700900125")
    _chat(db, "acc-1", "ignored", phone="447700900126")
    _chat(db, "acc-1", "old", phone="447700900127", minutes=60 * 24 * 3)
    _chat(db, "acc-1", "outbound-only", phone="447700900128", direction="out")
    _chat(db, "acc-off", "off-lead", phone="447700900129")
    db.add(ClientDeskWaLink(account_uid="acc-1", conversation_uid="linked", company_id=801, link_type="linked"))
    db.add(ClientDeskWaLink(account_uid="acc-1", conversation_uid="ignored", link_type="ignored"))
    db.commit()


def _scan_and_drain(env):
    queued = wa.scan(env.factory, env.cfg.CLIENT_DESK_UNLINKED_DAILY_QUOTA)
    worker.drain_queue(env.factory, limit=10)
    return queued


def _lead(db):
    return db.query(ClientDeskUnlinkedThread).filter_by(channel=wa.CHANNEL, thread_key="lead").one()


def test_scan_admits_only_recent_one_to_one_customer_chats_on_authorised_numbers(env):
    assert _scan_and_drain(env) == 1
    with env.factory() as db:
        assert [t.thread_key for t in db.query(ClientDeskUnlinkedThread).all()] == ["lead"]
        result = service.list_threads(db, USER)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["channel"] == "whatsapp"
    assert item["display_name"] == "Maria"
    assert item["company_hint"] == "+447****0123"
    assert item["run"]["one_line_summary"] == GOOD["one_line_summary"]
    assert env.calls and env.calls[0]["caller_module"] == "client_desk_unlinked"
    assert "22 inch #613" in env.calls[0]["messages"][0]["content"]


def test_second_scan_does_not_reanalyse_until_a_new_inbound_message(env):
    _scan_and_drain(env)
    assert _scan_and_drain(env) == 0
    with env.factory() as db:
        db.add(WhatsAppMessage(account_uid="acc-1", conversation_uid="lead", message_uid="m-new",
                               external_message_id="e-new", direction="in", content_text="Price for 10 pcs?",
                               sent_at=beijing_now()))
        db.commit()
    # The daily slot is used; a new inbound waits for tomorrow's quota or a manual re-run.
    assert _scan_and_drain(env) == 0
    with env.factory() as db:
        run = service.request_analysis(db, USER, _lead(db).id)
    assert run["status"] == "queued"
    worker.drain_queue(env.factory)
    assert len(env.calls) == 2


def test_withdrawing_the_switch_hides_threads_and_stops_queued_runs(env):
    wa.scan(env.factory, 20)
    with env.factory() as db:
        db.query(WhatsAppAccount).filter_by(account_uid="acc-1").update({"unlinked_ai_allowed": False})
        db.commit()
    worker.drain_queue(env.factory)
    assert env.calls == []
    with env.factory() as db:
        assert db.query(ClientDeskUnlinkedRun).one().error_code == "authority_revoked"
        with pytest.raises(HTTPException) as exc:
            service.list_threads(db, USER)
        assert exc.value.status_code == 403


def test_consent_change_marks_earlier_analysis_stale(env):
    _scan_and_drain(env)
    with env.factory() as db:
        db.query(WhatsAppAccount).filter_by(account_uid="acc-1").update({"consent_version": 3})
        db.commit()
        # Not shown until the next scan re-reads the chat under the new grant.
        assert service.list_threads(db, USER)["total"] == 0
    wa.scan(env.factory, 20)
    with env.factory() as db:
        item = service.list_threads(db, USER)["items"][0]
    assert item["analysis_stale"] and item["run"] is None


def test_deleted_message_invalidates_the_analysis(env):
    _scan_and_drain(env)
    with env.factory() as db:
        db.query(WhatsAppMessage).filter_by(message_uid="m-lead").update({"deleted_at": beijing_now()})
        db.commit()
        item = service.list_threads(db, USER)["items"][0]
    assert item["analysis_stale"] and item["run"] is None


def test_not_a_customer_writes_the_desk_link_wipes_output_and_can_be_undone(env):
    _scan_and_drain(env)
    with env.factory() as db:
        thread_id = _lead(db).id
        service.ignore(db, USER, thread_id)
        link = db.query(ClientDeskWaLink).filter_by(conversation_uid="lead", deleted_at=None).one()
        assert link.link_type == "ignored"
        run = db.query(ClientDeskUnlinkedRun).one()
        assert run.status == "wiped" and run.one_line_summary is None and run.draft_message is None
        assert service.list_threads(db, USER)["total"] == 0
        restored = service.restore(db, USER, thread_id)
        assert restored["status"] == "active"
        assert db.query(ClientDeskWaLink).filter_by(conversation_uid="lead", deleted_at=None).first() is None


def test_bind_creates_the_desk_link_and_removing_it_returns_the_chat(env):
    _scan_and_drain(env)
    with env.factory() as db:
        thread_id = _lead(db).id
        bound = service.bind(db, USER, thread_id, "801")
        assert bound["status"] == "linked" and bound["link"]["company_id"] == "801"
        link = db.query(ClientDeskWaLink).filter_by(conversation_uid="lead", deleted_at=None).one()
        assert link.link_type == "linked"
        link.deleted_at = beijing_now()
        db.commit()
    wa.scan(env.factory, 20)
    with env.factory() as db:
        assert _lead(db).status == "active"


def test_link_made_on_the_conversations_page_takes_the_thread_out(env):
    _scan_and_drain(env)
    with env.factory() as db:
        db.add(ClientDeskWaLink(account_uid="acc-1", conversation_uid="lead", link_type="ignored"))
        db.commit()
        assert service.list_threads(db, USER)["total"] == 0
    wa.scan(env.factory, 20)
    with env.factory() as db:
        assert _lead(db).status == "ignored"
        assert db.query(ClientDeskUnlinkedRun).one().status == "wiped"


def test_daily_quota_is_counted_per_channel(env):
    with env.factory() as db:
        tm = ClientDeskUnlinkedThread(user_id=1, channel=worker.CHANNEL, source_account_uid="src",
                                      thread_key="conv:x", status="active", seen_watermark=[1, 0])
        db.add(tm)
        db.flush()
        db.add(ClientDeskUnlinkedRun(thread_id=tm.id, user_id=1, biz_date=wa.beijing_today(),
                                     trigger_type="daily", run_seq=0, status="succeeded", attempts=1))
        db.commit()
    assert wa.scan(env.factory, 1) == 1


def test_whatsapp_threads_never_reach_another_user(env):
    _scan_and_drain(env)
    with env.factory() as db:
        with pytest.raises(HTTPException):
            service.list_threads(db, {"sub": "3"})
        with pytest.raises(HTTPException) as exc:
            service.handled(db, {"sub": "3"}, _lead(db).id)
        assert exc.value.status_code in (403, 404)


def test_weekly_review_covers_whatsapp_reps(env):
    _scan_and_drain(env)
    with env.factory() as db:
        db.query(ClientDeskUnlinkedRun).update({"biz_date": wa.beijing_today() - timedelta(days=7)})
        db.commit()

    def weekly_chat(db, **kwargs):
        thread_id = str(db.query(ClientDeskUnlinkedThread.id).filter_by(thread_key="lead").scalar())
        return {"content": json.dumps({"overview_md": "本周一条 WhatsApp 线索", "missed_tasks": [
            {"thread_id": thread_id, "title": "回复库存", "evidence": "客户问现货", "suggested_action": "今天回复"}],
            "breakthrough_leads": [], "likely_existing_customers": [], "cleanup_candidates": []}),
            "finish_reason": "stop"}

    env.monkeypatch.setattr(worker, "chat", weekly_chat)
    env.monkeypatch.setattr(worker, "prepare_text_chat", wa.prepare_text_chat)
    assert worker.weekly_for_reps(env.factory) == {1: "succeeded"}
    with env.factory() as db:
        review = service.list_reviews(db, USER)["items"][0]
    assert review["missed_tasks"][0]["title"] == "回复库存"


def test_switch_requires_crm_sharing_and_ai_egress(env, monkeypatch):
    class Connector:
        def reauthorize_account(self, uid):
            return {}

        def pause_account(self, uid):
            return {}

    monkeypatch.setattr(lifecycle, "WhatsAppConnectorClient", Connector)
    with env.factory() as db:
        account = db.query(WhatsAppAccount).filter_by(account_uid="acc-off").one()
        monkeypatch.setattr(lifecycle, "owned_account", lambda db, uid, actor: account)
        actor = {"sub": "3", "roles": [], "permissions": []}
        lifecycle.update_consent(db, "acc-off", actor, enabled=True, crm_shared=True, reader_user_ids=[],
                                 ai_egress_allowed=False, unlinked_ai_allowed=True)
        assert account.unlinked_ai_allowed is False
        lifecycle.update_consent(db, "acc-off", actor, enabled=True, crm_shared=True, reader_user_ids=[],
                                 ai_egress_allowed=True, unlinked_ai_allowed=True)
        assert account.unlinked_ai_allowed is True
        lifecycle.update_consent(db, "acc-off", actor, enabled=False, crm_shared=True, reader_user_ids=[],
                                 ai_egress_allowed=True, unlinked_ai_allowed=True)
        assert account.unlinked_ai_allowed is False
