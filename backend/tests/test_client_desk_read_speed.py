"""Read latency budgets and authorization boundaries, using isolated SQLite."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.client_desk import access, private_scope, read_scope, service, sources, timeline
from app.client_desk.models import ClientDeskSuggestion, ClientDeskWaLink, ClientDeskFollowup
from app.client_desk.source_context import list_last_touches
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage
from app.auth.models import ArkUser
from tests.test_client_desk_business import isolated

REAL_SCOPED = service.scoped
REAL_VISIBLE_WA = sources.visible_wa


@pytest.fixture(autouse=True)
def clear_cache():
    read_scope._cache.clear()
    yield
    read_scope._cache.clear()


def test_detail_assembles_once_and_reuses_sources_for_brief(isolated, monkeypatch):
    db = isolated
    calls = []
    monkeypatch.setattr(private_scope, "check_availability", lambda *a, **k: calls.append(k) or {"status": "active"})
    original = sources.build_customer_sources
    state = service.lock_state(db, 1, 801)
    state.brief_md = "Current brief"
    state.brief_dependencies = original(db, 1, 801, realtime=False)["ai_source_dependencies"]
    db.commit()
    builds = []
    monkeypatch.setattr(sources, "build_customer_sources", lambda *a, **kw: builds.append(1) or original(*a, **kw))
    lists = []
    original_list = private_scope._list_private_companies
    monkeypatch.setattr(private_scope, "_list_private_companies", lambda *a: lists.append(1) or original_list(*a))
    result = service.detail(db, 1, 801)
    assert result["brief_md"] == "Current brief"
    assert len(builds) == len(calls) == len(lists) == 1


def test_read_ttl_shared_across_dossier_timeline_and_event_and_expires(isolated, monkeypatch):
    db = isolated
    clock = [0]
    calls = []
    monkeypatch.setattr(read_scope, "monotonic", lambda: clock[0])
    monkeypatch.setattr(private_scope, "check_availability", lambda *a, **k: calls.append(k) or {"status": "active"})
    service.detail(db, 1, 801)
    with Session(db.get_bind()) as second:
        timeline.timeline(second, 1, 801)
        timeline.event(second, 1, 801, "created:801")
    assert len(calls) == 1
    clock[0] = 59.99
    service.detail(db, 1, 801)
    assert len(calls) == 1
    clock[0] = 60
    service.detail(db, 1, 801)
    assert len(calls) == 2


def test_scope_cache_separates_users_bindings_customers_and_engines(isolated, monkeypatch):
    calls, binding = [], [11]
    monkeypatch.setattr(private_scope, "resolve_okki_user_id", lambda *a: binding[0])
    monkeypatch.setattr(private_scope, "check_availability", lambda *a, **k: calls.append(k) or {"status": "active"})
    read = read_scope.scope_request(read_only=True)(private_scope.assert_company_access)
    read(isolated, 1, 801)
    read(isolated, 1, 801)
    read(isolated, 2, 801)
    read(isolated, 1, 802)
    binding[0] = 12
    read(isolated, 1, 801)
    from sqlalchemy import create_engine
    with Session(create_engine("sqlite://")) as second:
        read(second, 1, 801)
    assert len(calls) == 5


def test_new_transfer_refreshes_missing_card_and_departure_returns_404(isolated, monkeypatch):
    clock = [0]
    monkeypatch.setattr(read_scope, "monotonic", lambda: clock[0])
    monkeypatch.setattr(private_scope, "check_availability", lambda *a, **kw: {"status": "active"})
    service.detail(isolated, 1, 801)
    isolated.execute(text("INSERT INTO lsordertest.customer_info VALUES(803,'New','US','[11]',NULL,NULL)"))
    isolated.commit()
    assert service.detail(isolated, 1, 803)["card"]["name"] == "New"
    isolated.execute(text("UPDATE lsordertest.customer_info SET owner_user_ids='[22]' WHERE company_id=801"))
    isolated.commit()
    clock[0] = 45
    with pytest.raises(HTTPException) as exc:
        service.detail(isolated, 1, 801)
    assert exc.value.status_code == 404


def test_list_live_dependency_checks_do_not_use_dossier_ownership_cache(isolated, monkeypatch):
    from app.client_desk import queue
    calls = []
    monkeypatch.setattr(private_scope, "check_availability", lambda *a, **kw: calls.append(1) or {"status": "active"})
    service.detail(isolated, 1, 801)
    isolated.add(ClientDeskSuggestion(user_id=1, company_id=801, biz_date=service.beijing_today(), run_seq=1))
    isolated.commit()
    def visible(db, row, *a):
        private_scope.assert_company_access(db, row.user_id, row.company_id)
        private_scope.assert_company_access(db, row.user_id, row.company_id)
        return {"rule_codes": [], "reason": "Current"}
    monkeypatch.setattr(queue, "visible_suggestion", visible)
    service.customer_list(isolated, 1, filter="suggested")
    assert len(calls) == 2  # Fresh for the list, deduplicated within that request.


def test_live_verification_serializes_against_read_cache_fill():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    started, release, reading = Event(), Event(), Event()
    key = ("ownership", "concurrent")
    read_scope.cached(key, 60, lambda: "old-grant")
    def denied():
        raise HTTPException(404, "Transferred")
    def live():
        started.set()
        assert release.wait(2)
        denied()
    def read():
        reading.set()
        return read_scope.cached(key, 60, denied)
    with ThreadPoolExecutor(max_workers=2) as pool:
        action = pool.submit(read_scope.fresh, key, live)
        assert started.wait(2)
        pending = pool.submit(read)
        try:
            assert reading.wait(2)
            assert not pending.done()
        finally:
            release.set()
        for future in (action, pending):
            with pytest.raises(HTTPException):
                future.result(timeout=2)
    assert key not in read_scope._cache


@pytest.mark.parametrize("outcome,status", [("out_of_scope", 404), (RuntimeError("offline"), 503)])
def test_failed_verification_is_not_cached(isolated, monkeypatch, outcome, status):
    calls = []
    def check(*a, **kw):
        calls.append(1)
        if isinstance(outcome, Exception):
            raise outcome
        return {"status": outcome}
    monkeypatch.setattr(private_scope, "check_availability", check)
    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            service.detail(isolated, 1, 801)
        assert exc.value.status_code == status
    assert len(calls) == 2


@pytest.mark.parametrize("action", ["copy", "wa", "state", "grade", "followup", "feedback"])
def test_sensitive_actions_bypass_warm_read_cache(isolated, monkeypatch, action):
    from app.client_desk import schemas
    db, status, calls = isolated, ["active"], []
    monkeypatch.setattr(service, "scoped", REAL_SCOPED)
    monkeypatch.setattr(private_scope, "check_availability", lambda *a, **kw: calls.append(1) or {"status": status[0]})
    row = ClientDeskSuggestion(user_id=1, company_id=801, biz_date=service.beijing_today(), run_seq=1)
    db.add(row)
    db.commit()
    service.detail(db, 1, 801)
    status[0] = "out_of_scope"
    actions = {
        "copy": lambda: service.fresh_detail(db, 1, 801),
        "wa": lambda: service.wa_open(db, 1, 801, SimpleNamespace(account_uid="a", conversation_uid="c")),
        "state": lambda: service.patch_state(db, 1, 801, schemas.StatePatch(expected_version=0, remark="changed")),
        "grade": lambda: service.put_grade(db, 1, 801, SimpleNamespace()),
        "followup": lambda: service.add_followup(db, 1, 801, SimpleNamespace()),
        "feedback": lambda: service.feedback(db, 1, row.id, SimpleNamespace()),
    }
    with pytest.raises(HTTPException) as exc:
        actions[action]()
    assert exc.value.status_code == 404 and len(calls) == 2
    # A fresh denial also evicts the previous read grant.
    with pytest.raises(HTTPException):
        service.detail(db, 1, 801)
    assert len(calls) == 3


def test_list_cache_covers_search_and_paging_but_expires_at_45_seconds(isolated, monkeypatch):
    calls, clock = [], [0]
    original = private_scope._list_private_companies
    monkeypatch.setattr(read_scope, "monotonic", lambda: clock[0])
    monkeypatch.setattr(private_scope, "_list_private_companies", lambda *a: calls.append(1) or original(*a))
    assert service.customer_list(isolated, 1)["total"] == 1
    service.customer_list(isolated, 1, keyword="Vis", page_size=1)
    clock[0] = 44.99
    service.customer_list(isolated, 1, page=2, page_size=1)
    assert len(calls) == 1
    clock[0] = 45
    service.customer_list(isolated, 1)
    assert len(calls) == 2


def test_all_evaluates_only_page_and_keeps_expired_rank_but_suggested_is_live(isolated, monkeypatch):
    from app.client_desk import queue
    db = isolated
    db.execute(text("DELETE FROM lsordertest.customer_info"))
    for cid in range(1, 51):
        db.execute(text("INSERT INTO lsordertest.customer_info VALUES(:cid,:name,'US','[11]',NULL,NULL)"), {"cid": cid, "name": f"Customer {cid}"})
        db.add(ClientDeskSuggestion(user_id=1, company_id=cid, biz_date=service.beijing_today(), run_seq=1, rank_score=100-cid))
    db.commit()
    seen = []
    monkeypatch.setattr(queue, "visible_suggestion", lambda db, row, *a: seen.append(row.company_id) or (None if row.company_id == 1 else {"reason": "Due", "rule_codes": ["R2_FOLLOWUP_DUE"]}))
    page = service.customer_list(db, 1, page_size=20)
    assert page["total"] == 50 and seen == list(range(1, 21))
    assert page["items"][0]["company_id"] == "1"
    assert page["items"][0]["rank_score"] == 99
    assert page["items"][0]["reason"] is None and page["items"][0]["suggestion_id"] is None
    seen.clear()
    suggested = service.customer_list(db, 1, filter="suggested", page_size=20)
    assert suggested["total"] == 49 and len(seen) == 50
    assert suggested["items"][0]["company_id"] == "2"
    assert service.customer_list(db, 1, reason="R2_FOLLOWUP_DUE")["total"] == 49


def test_aggregate_touch_and_message_projection_keep_live_source_acl(isolated, monkeypatch):
    db = isolated
    monkeypatch.setattr(sources, "visible_wa", REAL_VISIBLE_WA)
    db.add(ArkUser(id=1, username="reader", real_name="Reader", password_hash="unused", is_active=True))
    account = WhatsAppAccount(account_uid="a", ark_user_id=1, status="active", consent_state="active", crm_shared=True)
    db.add(account)
    db.add(WhatsAppConversation(account_uid="a", conversation_uid="c", chat_id="chat", is_group=False))
    db.add(ClientDeskWaLink(account_uid="a", conversation_uid="c", company_id=801, link_type="linked", created_by=1))
    now = datetime(2026, 11, 12, 10)
    for i in range(100):
        db.add(WhatsAppMessage(message_uid=f"m{i}", external_message_id=str(i), account_uid="a", conversation_uid="c", direction="in", content_text="Needed", raw_payload={"large": "Unused" * 100}, received_at=now + timedelta(minutes=i), deleted_at=now if i == 99 else None))
    db.add(ClientDeskFollowup(user_id=1, company_id=801, happened_at=now, channel="phone", content="Called", client_request_id="call"))
    db.commit()
    sql = []
    def capture(conn, cursor, statement, *args):
        sql.append(statement.lower())
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert list_last_touches(db, {"sub": "1"}, ["801"])["801"] == (now + timedelta(minutes=98), "whatsapp")
        message_queries = [s for s in sql if "ark_whatsapp_messages" in s]
        assert len(message_queries) == 1 and "max(coalesce(" in message_queries[0]
        assert "content_text" not in message_queries[0] and "raw_payload" not in message_queries[0]
        sql.clear()
        rows = REAL_VISIBLE_WA(db, 1, 801)[0][2]
        assert len(rows) == 99 and rows[0].content_text == "Needed"
        message_query = next(s for s in sql if "from ark_whatsapp_messages" in s)
        assert "raw_payload" not in message_query and "sender_phone" not in message_query
        account.crm_shared = False
        db.commit()
        assert list_last_touches(db, {"sub": "1"}, ["801"])["801"] == (now, "phone")
        assert REAL_VISIBLE_WA(db, 1, 801) == []
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
