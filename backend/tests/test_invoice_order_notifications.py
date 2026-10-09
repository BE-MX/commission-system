"""Daily Ark order notices use an isolated SQLite database and mocked DingTalk."""

from datetime import date, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.festival import notification_service
from app.festival.models import FestivalEvent, FestivalState
from app.invoice.models import Invoice, InvoiceSyncLog


def invoice(db, no, *, amount=100, new=0, sync="synced", status="synced",
            currency="USD", fee=0, day=date(2026, 10, 9), remote=None):
    row = Invoice(
        invoice_no=no, customer_id="C1", customer_name="Customer",
        sales_user_id=101, sales_user_name="Salesperson", invoice_date=day,
        total_amount=amount, surcharge_amount=fee, currency=currency,
        okki_new_deal=new, sync_status=sync, status=status,
        xiaoman_order_id=remote or f"remote-{no}",
    )
    db.add(row)
    db.flush()
    return row


def detect(db):
    from app.invoice.order_notification_service import detect_order_events
    return detect_order_events(db)


def test_first_enable_baselines_history_without_messages(db):
    invoice(db, "old", amount=40000, new=1, day=date(2026, 8, 1))
    assert detect(db) == 0
    assert detect(db) == 0
    assert db.query(FestivalEvent).count() == 0


def test_baseline_shards_keep_late_sync_and_new_shards(db):
    import json

    old = invoice(db, "old")
    old.id = 999
    late = invoice(db, "late", sync="not_synced", new=1)
    late.id = 1000
    db.flush()
    assert detect(db) == 0
    late.sync_status = "synced"
    assert detect(db) == 1
    newer = invoice(db, "newer", new=1)
    newer.id = 2000
    db.flush()
    assert detect(db) == 1
    assert detect(db) == 0
    shards = db.query(FestivalState).filter(
        FestivalState.state_key.like("baseline:daily:ark:invoice_orders:%"),
    ).all()
    assert sorted(json.loads(s.value_json)["invoice_ids"] for s in shards) == [[999], [1000], [2000]]
    # Even 1000 IDs at the largest possible BIGINT width stay below MySQL TEXT's limit.
    largest = [2**63 - 1 - i for i in range(1000)]
    assert len(json.dumps({"invoice_ids": largest}).encode()) < 65535


@pytest.mark.parametrize("day", [date(2026, 7, 1), date(2026, 10, 9), date(2027, 1, 1)])
def test_all_dates_and_three_notice_types(db, day):
    detect(db)
    invoice(db, "new", new=1, day=day)
    invoice(db, "ordinary", day=day)
    invoice(db, "big", amount=5000, day=day)
    invoice(db, "super", amount=30000, day=day)
    invoice(db, "below", amount=5100, fee=101, day=day)
    assert detect(db) == 3
    events = db.query(FestivalEvent).all()
    assert {e.event_type for e in events} == {
        "new_sign_order", "big_deal", "super_deal",
    }
    assert [e.dedup_key for e in events if e.event_type == "big_deal"] == ["deal:remote-big"]
    assert [e.dedup_key for e in events if e.event_type == "super_deal"] == ["deal:remote-super"]
    assert detect(db) == 0


def test_drafts_failures_cancellation_and_later_success(db):
    pending = invoice(db, "draft", sync="not_synced", status="draft", new=1)
    detect(db)
    invoice(db, "failed", sync="sync_failed")
    invoice(db, "uncertain", sync="sync_uncertain")
    invoice(db, "cancelled", status="cancelled")
    invoice(db, "cancel-pending", status="cancel_pending")
    assert detect(db) == 0
    pending.sync_status = "synced"
    pending.status = "synced"
    assert detect(db) == 1
    pending.sync_status = "sync_failed"
    detect(db)
    pending.sync_status = "synced"
    pending.total_amount = 30000
    assert detect(db) == 0


def test_same_order_has_no_duplicate_festival_notice(db):
    detect(db)
    invoice(db, "new", amount=5000, new=1)
    for kind, key in [("new_sign_order", "new_sign:remote-new"), ("big_deal", "deal:remote-new")]:
        db.add(FestivalEvent(
            event_type=kind, dedup_key=key, level="L3", subject_type="person",
            subject_id="U1", subject_name="Salesperson",
        ))
    db.flush()
    assert detect(db) == 0
    assert db.query(FestivalEvent).count() == 2


def test_non_usd_is_never_classified_as_usd_big_deal(db):
    detect(db)
    invoice(db, "cny", amount=30000, currency="CNY", new=1)
    assert detect(db) == 1
    event = db.query(FestivalEvent).one()
    assert event.event_type == "new_sign_order"
    assert event.amount is None
    assert "CNY 30,000" in event.detail


def test_notice_detail_hides_customer_and_uses_country_overlay(db):
    from sqlalchemy import text
    from app.invoice.models import InvoiceCustomerOverlay

    detect(db)
    db.execute(text("INSERT INTO lsordertest.customer_info (company_id, company_name, country_name) "
                    "VALUES ('C1', 'Customer', 'United States')"))
    invoice(db, "no-number-in-card", amount=35000)
    assert detect(db) == 1
    assert {event.detail for event in db.query(FestivalEvent).all()} == {
        "恭喜未分队的Salesperson成交United States的客户！"}
    db.add(InvoiceCustomerOverlay(company_id="C1", company_name="Customer", country_name="Canada"))
    invoice(db, "overlay", currency="CNY", amount=35000, new=1)
    assert detect(db) == 1
    assert db.query(FestivalEvent).order_by(FestivalEvent.id.desc()).first().detail == (
        "恭喜未分队的Salesperson新签Canada的客户！\nCNY 35,000")


@pytest.mark.parametrize("kind", ["new_sign_order", "big_deal", "super_deal"])
def test_order_card_has_alpha_glass_and_actual_board_avatar(tmp_path, monkeypatch, kind):
    from PIL import Image
    from app.festival import order_card_renderer

    root = tmp_path / "repo"
    avatar = root / "frontend/public/festival/assets/avatars/U1.png"
    avatar.parent.mkdir(parents=True)
    Image.new("RGB", (180, 180), (200, 40, 60)).save(avatar)
    monkeypatch.setattr(notification_service, "_REPO_ROOT", root)
    monkeypatch.setattr(notification_service, "_UPLOAD_ROOT", tmp_path / "output")
    event = {
        "event_type": kind, "label": "超级大单", "subject_type": "person", "subject_id": "U1",
        "subject_name": "业务员", "detail": "恭喜先锋战队的业务员成交美国的客户！", "amount": 35000,
        "dedup_key": f"glass:{kind}", "created_at": datetime(2026, 10, 9, 11, 40),
    }
    image_path = notification_service.render_event_image(event)
    assert image_path.stat().st_size < 200 * 1024
    with Image.open(image_path) as image:
        assert image.format == "PNG" and image.size == (800, 450)
        image = image.convert("RGBA")
        assert image.getpixel((0, 0))[3] == 0
        assert all(abs(a - b) < 20 for a, b in zip(
            image.getpixel((133, 200)), (200, 40, 60, 255)))
        assert image.getpixel((433, 287))[3] > 0
    # Delivery reads content dynamically; the material asset cannot contain sample data.
    words = []
    original = order_card_renderer._engrave
    def record(image, position, value, font, **kwargs):
        words.append(value)
        return original(image, position, value, font, **kwargs)
    monkeypatch.setattr(order_card_renderer, "_engrave", record)
    event.update(detail="恭喜乘风破浪战队的业务员新签United States的客户！", amount=None)
    notification_service.render_event_image(event)
    assert "恭喜乘风破浪战队的业务员新签United States的客户！" in "".join(words)
    assert not any("…" in value for value in words)
    assert not any("SO-" in value or "$35,000" in value for value in words)


def test_blank_new_sign_flag_uses_successful_push_evidence(db):
    import json
    from app.invoice.xiaoman_service import FIELD_NEW_DEAL

    detect(db)
    row = invoice(db, "auto-new", new=None)
    db.add(InvoiceSyncLog(
        invoice_id=row.id, action="create", success=1,
        request_digest=json.dumps({FIELD_NEW_DEAL: "是"}),
    ))
    db.add(InvoiceSyncLog(
        invoice_id=row.id, action="update", success=0,
        request_digest=json.dumps({FIELD_NEW_DEAL: "否"}),
    ))
    db.flush()
    assert detect(db) == 1
    assert db.query(FestivalEvent).one().event_type == "new_sign_order"


def test_current_push_execution_saves_auto_new_sign_evidence(db, monkeypatch):
    import json
    from types import SimpleNamespace
    from app.invoice import order_sync_execution as execution
    from app.invoice.xiaoman_service import FIELD_NEW_DEAL

    detect(db)
    row = invoice(db, "auto-current", new=None, sync="sync_uncertain", status="sync_uncertain")
    attempt = SimpleNamespace(
        data={"action": "create"}, payload={FIELD_NEW_DEAL: "是", "product_list": [], "remark": "private"},
        key="attempt-1", actor_id=1, inventory_key=None, receipt_token=None,
    )
    monkeypatch.setattr(execution, "verified_response", lambda *_args: [])
    monkeypatch.setattr(execution.xiaoman_service, "get_settings_row", lambda _db: None)
    monkeypatch.setattr(execution.xiaoman_service, "_build_product_rows", lambda *_args, **_kw: ([], [], [], []))
    monkeypatch.setattr(execution.xiaoman_service, "get_settings", lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=False))
    monkeypatch.setattr(execution.inventory, "finalize_invoice_sync", lambda *_args: None)
    monkeypatch.setattr(execution.invoice_link, "mark_success", lambda *_args: {})
    monkeypatch.setattr(execution.invoice_link, "finish_attempt", lambda *_args: None)
    result = execution.apply(db, row, attempt, {
        "result_class": "accepted", "provider_reference": "remote-auto-current",
    }, {})
    db.flush()
    assert result["ok"] is True
    assert row.sync_status == "synced"
    assert json.loads(db.query(InvoiceSyncLog).one().request_digest) == {FIELD_NEW_DEAL: "是"}
    assert detect(db) == 1
    assert db.query(FestivalEvent).one().event_type == "new_sign_order"


@pytest.mark.parametrize("kind", ["new_sign_order", "big_deal", "super_deal"])
def test_order_image_footer_has_no_festival_date(kind):
    assert notification_service._event_brand({"event_type": kind}) == "方舟订单"
    assert notification_service._event_brand({"event_type": "rank_up_sign"}) == "2026 莱莎采购节"


def test_monitor_loads_daily_events_without_festival_board(engine, monkeypatch):
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    monkeypatch.setattr(notification_service, "beijing_now", lambda: datetime(2026, 10, 9, 12))
    monkeypatch.setattr(notification_service.service, "get_headline_payload",
                        lambda *_args: pytest.fail("Daily notices must not depend on the festival board"))
    assert notification_service._detect_and_load_pending() == []
    with factory() as db:
        invoice(db, "daily", new=1)
        db.commit()
    pending = notification_service._detect_and_load_pending()
    assert [e["event_type"] for e in pending] == ["new_sign_order"]


@pytest.mark.asyncio
async def test_delivery_uses_daily_branding(engine, monkeypatch):
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    monkeypatch.setattr(notification_service, "beijing_now", lambda: datetime(2026, 10, 9, 12))
    notification_service._detect_and_load_pending()
    with factory() as db:
        invoice(db, "placed", new=1)
        db.commit()
    sent = []

    class Sender:
        async def send_markdown(self, title, markdown):
            sent.append((title, markdown))

    monkeypatch.setattr(notification_service, "_festival_sender", lambda: Sender())
    monkeypatch.setattr(notification_service, "render_event_image", lambda _e: None)
    monkeypatch.setattr(notification_service, "_public_url", lambda _p: "https://files.test/notice.png")
    assert (await notification_service.monitor_festival_events())["sent"] == 1
    assert sent[0][0] == "方舟订单 · 新签喜报"
    assert "Customer" not in sent[0][1]
    assert "恭喜未分队的Salesperson新签国家未知的客户！" in sent[0][1]
    assert (await notification_service.monitor_festival_events())["sent"] == 0


def test_ordinary_orders_are_observed_without_notices(db):
    detect(db)
    row = invoice(db, "ordinary", amount=4999)
    assert detect(db) == 0
    row.total_amount = 35000
    row.okki_new_deal = 1
    assert detect(db) == 0
    assert db.query(FestivalEvent).count() == 0


def test_team_comes_from_active_okki_binding(db):
    from sqlalchemy import text
    from app.auth.models import ArkUser, ArkUserExternalBinding

    db.execute(text("CREATE TABLE lsordertest.user_rel_team (user_id TEXT, Team TEXT)"))
    db.execute(text("INSERT INTO lsordertest.user_rel_team VALUES ('U1', '先锋战队')"))
    db.add(ArkUser(id=101, username="salesperson", real_name="Salesperson", password_hash="test"))
    db.add(ArkUserExternalBinding(ark_user_id=101, provider="okki", external_account_id="U1",
                                binding_status="active"))
    db.flush()
    detect(db)
    invoice(db, "new-big", new=1, amount=5000)
    assert detect(db) == 2
    assert {row.detail for row in db.query(FestivalEvent)} == {
        "恭喜先锋战队的Salesperson新签国家未知的客户！"}
    from app.invoice.order_notification_service import delivery_order_detail
    event = notification_service._event_dict(db.query(FestivalEvent).first())
    event.update(subject_id="ark:101", detail="PRIVATE CUSTOMER")
    assert delivery_order_detail(db, event) == "恭喜先锋战队的Salesperson新签国家未知的客户！"
    db.query(ArkUserExternalBinding).one().binding_status = "inactive"
    db.flush()
    event["subject_id"] = "U1"
    assert delivery_order_detail(db, event) == "恭喜未分队的Salesperson新签国家未知的客户！"
    binding = db.query(ArkUserExternalBinding).one()
    binding.binding_status = "active"
    binding.deleted_at = datetime(2026, 10, 9, 12)
    db.flush()
    assert delivery_order_detail(db, event) == "恭喜未分队的Salesperson新签国家未知的客户！"


@pytest.mark.asyncio
async def test_legacy_pending_copy_is_redacted_and_other_event_types_stay_unsent(engine, monkeypatch):
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(notification_service, "SessionLocal", factory)
    monkeypatch.setattr(notification_service, "beijing_now", lambda: datetime(2026, 10, 9, 12))
    notification_service._detect_and_load_pending()
    with factory() as db:
        invoice(db, "legacy", amount=5000)
        for kind, key in [("big_deal", "deal:remote-legacy"),
                          ("order_placed", "order:remote-legacy"), ("rank_up_sign", "rank:legacy")]:
            db.add(FestivalEvent(event_type=kind, dedup_key=key, level="L3", subject_type="person",
                                 subject_id="ark:101", subject_name="Salesperson",
                                 detail="United States · PRIVATE CUSTOMER", amount=5000))
        db.commit()
    images, sent = [], []
    class Sender:
        async def send_markdown(self, title, markdown):
            sent.append(markdown)
    monkeypatch.setattr(notification_service, "_festival_sender", lambda: Sender())
    monkeypatch.setattr(notification_service, "render_event_image", lambda event: images.append(event) or None)
    monkeypatch.setattr(notification_service, "_public_url", lambda path: "https://files.test/card.png")
    assert (await notification_service.monitor_festival_events())["sent"] == 1
    assert images[0]["detail"] == "恭喜未分队的Salesperson成交国家未知的客户！"
    assert "PRIVATE CUSTOMER" not in sent[0]
    with factory() as db:
        assert db.query(FestivalEvent).filter(FestivalEvent.dingtalk_sent_at.is_(None)).count() == 2
