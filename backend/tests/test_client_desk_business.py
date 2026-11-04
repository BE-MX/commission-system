"""Business tests use isolated SQLite and attached read-only mirror fixtures."""

from datetime import datetime, date, timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.client_desk import service, schemas, sources, private_scope, access
from app.client_desk.models import (
    ClientDeskState,
    ClientDeskFollowup,
    ClientDeskSuggestion,
    ClientDeskWaLink,
)
from app.auth.models import ArkUser
from app.invoice.models import CustomerProfile, InvoiceCustomerOverlay
from app.system.models import SysDict


@pytest.fixture
def isolated(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.connection.driver_connection.create_collation(
            "utf8mb4_unicode_ci", lambda a, b: (a > b) - (a < b)
        )
        for sql in [
            "ATTACH DATABASE ':memory:' AS lsordertest",
            "CREATE TABLE lsordertest.customer_info(company_id BIGINT,company_name TEXT,country_name TEXT,owner_user_ids TEXT,create_time TEXT,update_time TEXT)",
            "CREATE TABLE lsordertest.customer_contacts(id BIGINT,company_id BIGINT,name TEXT,email TEXT,tel TEXT)",
            "CREATE TABLE lsordertest.okki_orders(order_id BIGINT,company_id BIGINT,order_no TEXT,account_date DATE,amount_usd NUMERIC,status TEXT,status_name TEXT,trail TEXT,name TEXT,sample_kind TEXT)",
            "CREATE TABLE ark_receivables(kind TEXT,remote_order_id TEXT,remote_order_name TEXT,customer_id TEXT)",
            "INSERT INTO lsordertest.customer_info VALUES(801,'Visible','US','[11]','2026-10-01 10:00:00','2026-11-01 00:00:00'),(802,'Other','UK','[111]','2026-10-01 10:00:00','2026-11-01 00:00:00')",
            "INSERT INTO lsordertest.customer_contacts VALUES(1,801,'Anna','anna@example.test','123')",
            "INSERT INTO lsordertest.okki_orders VALUES(1,801,'O1','2026-10-01',20,'13972831656','已结束',NULL,'goods','bulk'),(2,801,'O2','2026-10-02',NULL,'13972831656','已结束',NULL,'goods','sample')",
        ]:
            conn.execute(text(sql))
        conn.commit()
    for model in [
        ArkUser,
        CustomerProfile,
        InvoiceCustomerOverlay,
        SysDict,
        ClientDeskState,
        ClientDeskFollowup,
        ClientDeskSuggestion,
        ClientDeskWaLink,
    ]:
        model.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as db:
        monkeypatch.setattr(service, "scoped", lambda *a, **kw: {"sub": "1"})
        monkeypatch.setattr(service, "require_enabled", lambda *a, **kw: {"sub": "1"})
        monkeypatch.setattr(private_scope, "resolve_okki_user_id", lambda *a: 11)
        monkeypatch.setattr(sources, "research_sources", lambda *a: [])
        monkeypatch.setattr(access, "require_enabled", lambda *a, **kw: {"sub": "1"})
        monkeypatch.setattr(sources, "visible_wa", lambda *a, **kw: [])
        yield db
    engine.dispose()


def test_patch_preserves_ai_and_checks_version(isolated):
    db = isolated
    state = service.lock_state(db, 1, 801)
    state.brief_md = "AI"
    state.next_followup_remark = "keep"
    db.commit()
    result = service.patch_state(
        db, 1, 801, schemas.StatePatch(expected_version=0, remark="mine")
    )
    assert (
        result["manual_version"] == 1
        and state.brief_md == "AI"
        and state.next_followup_remark == "keep"
    )
    service.patch_state(db, 1, 801, schemas.StatePatch(expected_version=1, remark=None))
    assert state.remark is None
    with pytest.raises(HTTPException) as exc:
        service.patch_state(
            db, 1, 801, schemas.StatePatch(expected_version=0, remark="stale")
        )
    assert exc.value.status_code == 409


def test_grade_shared_cas_and_idempotent(isolated):
    db = isolated
    service.seed_grade_dictionary(db)
    db.commit()
    assert sources.grade_options(db) == list("SABCDE")
    service.put_grade(db, 1, 801, schemas.GradePut(grade="A", expected_grade=None))
    with pytest.raises(HTTPException) as exc:
        service.put_grade(db, 1, 801, schemas.GradePut(grade="B", expected_grade=None))
    assert exc.value.status_code == 409
    service.put_grade(db, 1, 801, schemas.GradePut(grade="A", expected_grade=None))
    assert db.query(CustomerProfile).one().customer_grade == "A"


def test_followup_timezone_idempotent_feedback_independent(isolated, monkeypatch):
    db = isolated
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 11, 4, 0, 1))
    row = ClientDeskSuggestion(
        user_id=1, company_id=801, biz_date=date(2026, 11, 4), status="succeeded"
    )
    db.add(row)
    db.commit()
    monkeypatch.setattr(service, "suggestion_for", lambda *a: row)
    payload = schemas.FollowupPost(
        channel="phone",
        content=" called ",
        happened_at=datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc),
        client_request_id="followup-1",
        suggestion_id=str(row.id),
    )
    first = service.add_followup(db, 1, 801, payload)
    second = service.add_followup(db, 1, 801, payload)
    assert first["event"]["id"] == second["event"]["id"]
    assert db.query(ClientDeskFollowup).one().happened_at == datetime(2026, 11, 4, 0, 0)
    service.feedback(db, 1, row.id, schemas.FeedbackPost(value="useful"))
    assert row.quality_feedback == "useful" and row.done_source == "manual_followup"


def test_mirror_sql_overlay_exact_owner_and_unknown_amount(isolated, monkeypatch):
    db = isolated
    monkeypatch.setattr(sources, "assert_company_access", lambda *a, **kw: None)
    assert [c["company_id"] for c in private_scope.list_private_companies(db, 1)] == [
        "801"
    ]
    db.add(
        InvoiceCustomerOverlay(
            company_id="802",
            company_name="Transferred in",
            owner_user_ids=[11],
            source_update_time="2026-11-03 00:00:00",
        )
    )
    monkeypatch.setattr(
        "app.invoice.product_service._table_columns", lambda *a: {"update_time"}
    )
    db.commit()
    assert [c["company_id"] for c in private_scope.list_private_companies(db, 1)] == [
        "801",
        "802",
    ]
    result = sources.build_customer_sources(db, 1, 801, realtime=False)
    assert (
        result["card"]["name"] == "Visible" and result["contacts"][0]["name"] == "Anna"
    )
    assert result["orders_summary"] == {
        "count": 2,
        "amount_usd": 20,
        "unknown_amount_count": 1,
    }
    assert len(result["refs"]) == 2 and result["in_transit"] is None


def test_calibrated_order_classification(monkeypatch):
    cfg = {
        "order_classification": {
            "sample_field": "sample_kind",
            "bulk_values": ["bulk"],
            "sample_values": ["sample"],
            "status_map": {
                "done": "completed",
                "ship": "in_transit",
                "cancel": "cancelled",
            },
        }
    }
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: SimpleNamespace(CLIENT_DESK_RULES=cfg)
    )
    orders = [
        {"status": "done", "sample_kind": "bulk", "account_date": date(2026, 1, 1)},
        {"status": "ship", "sample_kind": "sample", "account_date": date(2026, 2, 1)},
    ]
    days, transit, gaps = sources.classify_orders(orders, {})
    assert days == [date(2026, 1, 1)] and transit and not gaps
    orders.append({"status": "new", "sample_kind": "bulk"})
    assert sources.classify_orders(orders, {})[1] is None


def test_link_cas_rebind_and_revoke(isolated, monkeypatch):
    from app.client_desk import link_service
    from app.whatsapp.models import WhatsAppConversation

    db = isolated
    WhatsAppConversation.__table__.create(db.get_bind())
    db.add(
        WhatsAppConversation(
            id=1, account_uid="a", conversation_uid="c", chat_id="chat", is_group=False
        )
    )
    db.commit()
    monkeypatch.setattr(link_service, "require_enabled", lambda *a, **kw: {"sub": "1"})
    monkeypatch.setattr(link_service, "require_account", lambda *a, **kw: None)
    monkeypatch.setattr(link_service, "assert_company_access", lambda *a, **kw: None)
    payload = schemas.LinkPost(
        account_uid="a", conversation_uid="c", link_type="linked", company_id="801"
    )
    first = link_service.save_link(db, 1, payload)
    assert link_service.save_link(db, 1, payload)["id"] == first["id"]
    with pytest.raises(HTTPException) as exc:
        link_service.save_link(
            db,
            1,
            schemas.LinkPost(
                account_uid="a",
                conversation_uid="c",
                link_type="linked",
                company_id="802",
            ),
        )
    assert exc.value.status_code == 409
    second = link_service.save_link(
        db,
        1,
        schemas.LinkPost(
            account_uid="a",
            conversation_uid="c",
            link_type="linked",
            company_id="802",
            expected_link_id=first["id"],
        ),
    )
    assert second["id"] != first["id"]
    link_service.delete_link(db, 1, second["id"])
    assert db.query(ClientDeskWaLink).filter_by(deleted_at=None).count() == 0
    assert link_service.delete_link(db, 1, second["id"])["deleted_at"]


def test_timeline_equal_timestamp_strict_cursor(isolated, monkeypatch):
    from app.client_desk import timeline

    events = [
        {
            "id": str(i),
            "event_key": f"followup:{i}",
            "source": "followup" if i % 2 else "order",
            "occurred_at": datetime(2026, 11, 4, 12),
        }
        for i in range(8)
    ]
    monkeypatch.setattr(timeline, "all_events", lambda *a: events)
    keys = []
    cursor = None
    while True:
        page = timeline.timeline(isolated, 1, 801, cursor=cursor, limit=3)
        keys.extend(e["event_key"] for e in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(keys) == 8 and len(set(keys)) == 8
    first = timeline.timeline(isolated, 1, 801, limit=3)
    with pytest.raises(HTTPException):
        timeline.timeline(isolated, 1, 801, source="order", cursor=first["next_cursor"])


def test_scan_sources_never_runs_import_or_writes(isolated, monkeypatch):
    from app.client_desk import source_context, history_import

    db = isolated
    monkeypatch.setattr(
        source_context, "require_enabled", lambda *a, **kw: {"sub": "1"}
    )
    monkeypatch.setattr(
        history_import,
        "import_history",
        lambda *a: pytest.fail("read-only sources imported associations"),
    )
    # First collection read, without any prior import marker or personal state.
    before = db.query(SysDict).count()
    rows = sources.scan_inputs(db, 1)
    assert [r["company_id"] for r in rows] == ["801"]
    assert db.query(SysDict).count() == before
    assert db.query(ClientDeskWaLink).count() == 0
    assert not db.new and not db.dirty


def test_feedback_never_shortens_cooldown_and_same_value_is_noop(isolated, monkeypatch):
    db = isolated
    day = date(2026, 11, 4)
    monkeypatch.setattr(service, "beijing_today", lambda: day)
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 11, 4, 12))
    row = ClientDeskSuggestion(
        user_id=1,
        company_id=801,
        biz_date=day,
        status="succeeded",
        rule_codes=["R1_UNREPLIED"],
    )
    db.add(row)
    db.commit()
    monkeypatch.setattr(service, "suggestion_for", lambda *a: row)
    first = service.feedback(db, 1, row.id, schemas.FeedbackPost(value="useless"))
    feedback_at = row.feedback_at
    assert first["rule_cooldowns"]["R1_UNREPLIED"] == "2026-11-18"
    monkeypatch.setattr(service, "beijing_today", lambda: date(2026, 11, 5))
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 11, 5, 12))
    repeated = service.feedback(db, 1, row.id, schemas.FeedbackPost(value="useless"))
    assert (
        repeated["rule_cooldowns"]["R1_UNREPLIED"] == "2026-11-18"
        and row.feedback_at == feedback_at
    )
    done = service.feedback(db, 1, row.id, schemas.FeedbackPost(value="done"))
    assert done["quality_feedback"] == "useless" and done["done_at"] is not None
    assert done["rule_cooldowns"]["R1_UNREPLIED"] == "2026-11-18"


def test_all_visible_rule_cites_resolve_through_timeline_acl(isolated, monkeypatch):
    from app.client_desk import timeline, queue

    db = isolated
    source = {
        "created_at": datetime(2026, 11, 1),
        "card": {"name": "Owned"},
        "orders": [],
        "research": [],
        "messages": [],
    }
    monkeypatch.setattr(timeline, "build_customer_sources", lambda *a: source)
    codes = [
        "R1_UNREPLIED",
        "R7_AWAITING_CUSTOMER",
        "R3_RECHECK_DUE",
        "R5_REPURCHASE",
        "R6_LONG_SILENT",
        "R8_NEW_LEAD",
    ]
    row = ClientDeskSuggestion(
        user_id=1,
        company_id=801,
        biz_date=service.beijing_today(),
        rule_codes=codes,
        status="succeeded",
    )
    db.add(row)
    db.commit()
    monkeypatch.setattr(queue, "visible_suggestion", lambda *a: {"rule_codes": codes})
    for code in codes:
        assert timeline.event(db, 1, 801, "rule:" + code)["rule_code"] == code
    monkeypatch.setattr(queue, "visible_suggestion", lambda *a: None)
    with pytest.raises(HTTPException):
        timeline.event(db, 1, 801, "rule:R1_UNREPLIED")


def test_same_revision_message_mutation_changes_dependency_hash():
    from app.whatsapp.models import WhatsAppMessage

    message = WhatsAppMessage(
        id=1,
        source_revision=0,
        content_text="old",
        direction="in",
        sent_at=datetime(2026, 11, 4, 10),
    )
    first = sources.message_fingerprint(message)
    message.content_text = "replacement"
    message.direction = "out"
    assert sources.message_fingerprint(message) != first


def test_invalid_freight_private_order_cannot_supply_repurchase_days(monkeypatch):
    cfg = {
        "order_classification": {
            "sample_field": "sample_kind",
            "bulk_values": ["bulk"],
            "sample_values": ["sample"],
            "status_map": {"done": "completed"},
        }
    }
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: SimpleNamespace(CLIENT_DESK_RULES=cfg)
    )
    orders = [
        {
            "status": "done",
            "sample_kind": "bulk",
            "account_date": date(2026, 1, i),
            "valid_business": i == 1,
        }
        for i in (1, 2, 3)
    ]
    days, transit, gaps = sources.classify_orders(orders, {})
    assert days == [date(2026, 1, 1)] and transit is False and not gaps


def test_old_round_snooze_or_done_does_not_reorder_quality(isolated, monkeypatch):
    db = isolated
    day = date(2026, 11, 4)
    monkeypatch.setattr(service, "beijing_today", lambda: day)
    rows = [
        ClientDeskSuggestion(
            user_id=1, company_id=801, biz_date=day, run_seq=i, status="succeeded"
        )
        for i in (0, 1)
    ]
    db.add_all(rows)
    db.commit()
    monkeypatch.setattr(
        service,
        "suggestion_for",
        lambda db, user, sid: next(r for r in rows if r.id == int(sid)),
    )
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 11, 4, 9))
    service.feedback(db, 1, rows[0].id, schemas.FeedbackPost(value="useful"))
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 11, 4, 10))
    service.feedback(db, 1, rows[1].id, schemas.FeedbackPost(value="useless"))
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 11, 4, 11))
    service.feedback(
        db,
        1,
        rows[0].id,
        schemas.FeedbackPost(value="snoozed", date=date(2026, 11, 10)),
    )
    service.feedback(db, 1, rows[0].id, schemas.FeedbackPost(value="done"))
    assert rows[0].feedback_at == datetime(2026, 11, 4, 9)
    assert (
        max(rows, key=lambda r: (r.feedback_at, r.run_seq)).quality_feedback
        == "useless"
    )
    assert rows[0].snoozed_until == date(2026, 11, 10) and rows[0].done_at == datetime(
        2026, 11, 4, 11
    )
