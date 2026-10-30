from datetime import date, datetime

import pytest

from app.domestic_followup import followup_service
from app.domestic_followup.models import DomesticCustomerAlias, DomesticFollowupItem, DomesticFollowupTask
from app.domestic_followup.schemas import ConfirmIn, DirectSaveIn, DraftCreateIn
from tests.domestic_followup_helpers import make_customer, make_shipment, make_user, seed_dicts

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(followup_service, "beijing_today", lambda: TODAY)
    monkeypatch.setattr(followup_service, "_enqueue_urgent", lambda *a, **k: None)


def _ctx(user):
    return {"sub": str(user.id), "roles": [], "permissions": ["domestic_followup:read", "domestic_followup:write"]}


def test_direct_save_creates_items_tasks_and_is_idempotent(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_a")
    customer = make_customer(db, user, "服务店A")
    payload = DirectSaveIn(
        request_id="req-direct-a", customer_id=customer.id, raw_text="客户说色差，下周一再电话",
        channel="微信", state_changes=["竞争品牌增加"], next_date=date(2026, 11, 2), next_plan="问补货",
        next_method="电话",
        items=[{"kind": "content", "text": "月销 13 万"},
               {"kind": "issue", "text": "色差明显", "category": "色差", "severity": "一般"},
               {"kind": "suggestion", "text": "想要短视频素材", "category": "产品需求", "record_only": True}],
    )
    followup, pending_ocr = followup_service.direct_save(db, _ctx(user), payload)
    again, _ = followup_service.direct_save(db, _ctx(user), payload)
    assert again.id == followup.id and pending_ocr == []
    assert followup.status == "confirmed" and followup.followup_date == TODAY
    items = db.query(DomesticFollowupItem).filter_by(followup_id=followup.id).order_by(DomesticFollowupItem.id).all()
    assert [i.status for i in items] == [None, "open", "closed_no_action"]
    tasks = db.query(DomesticFollowupTask).filter_by(customer_id=customer.id).all()
    assert sorted(t.task_type for t in tasks) == ["issue", "plan"]


def test_direct_save_rejects_unknown_dict_value(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_b")
    customer = make_customer(db, user, "服务店B")
    with pytest.raises(ValueError, match="状态变化"):
        followup_service.direct_save(db, _ctx(user), DirectSaveIn(
            request_id="req-direct-b", customer_id=customer.id, raw_text="x", state_changes=["瞎编的状态"]))


def test_direct_save_requires_content(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_c")
    customer = make_customer(db, user, "服务店C")
    with pytest.raises(ValueError, match="跟进内容"):
        followup_service.direct_save(db, _ctx(user), DirectSaveIn(request_id="req-direct-c", customer_id=customer.id))


def test_dates_are_validated(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_d")
    customer = make_customer(db, user, "服务店D")
    db.commit()  # 第一次调用失败会 rollback；先提交夹具，第二次调用才找得到客户
    with pytest.raises(ValueError, match="下次跟进日期"):
        followup_service.direct_save(db, _ctx(user), DirectSaveIn(
            request_id="req-direct-d1", customer_id=customer.id, raw_text="x",
            followup_date=date(2026, 10, 28), next_date=date(2026, 10, 27)))
    with pytest.raises(ValueError, match="晚于今天"):
        followup_service.direct_save(db, _ctx(user), DirectSaveIn(
            request_id="req-direct-d2", customer_id=customer.id, raw_text="x", followup_date=date(2026, 10, 31)))


def test_draft_confirm_flow_with_version_and_alias(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_e")
    customer = make_customer(db, user, "服务店E")
    draft, _ = followup_service.create_draft(db, _ctx(user), DraftCreateIn(request_id="req-draft-e", raw_text="聊天内容"))
    assert draft.status == "draft" and draft.ai_status == "running" and draft.customer_id is None

    with pytest.raises(followup_service.ConflictError):
        followup_service.confirm_draft(db, _ctx(user), draft.id, ConfirmIn(version=99, customer_id=customer.id))

    confirmed = followup_service.confirm_draft(db, _ctx(user), draft.id, ConfirmIn(
        version=1, customer_id=customer.id, chat_title="E 店 老板", summary="摘要"))
    assert confirmed.status == "confirmed" and confirmed.version == 2
    assert db.query(DomesticCustomerAlias).filter_by(customer_id=customer.id, alias_norm="e店老板").one()
    with pytest.raises(followup_service.ConflictError):
        followup_service.confirm_draft(db, _ctx(user), draft.id, ConfirmIn(version=2, customer_id=customer.id))


def test_confirm_requires_customer(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_f")
    draft, _ = followup_service.create_draft(db, _ctx(user), DraftCreateIn(request_id="req-draft-f", raw_text="x"))
    with pytest.raises(ValueError, match="请选择客户"):
        followup_service.confirm_draft(db, _ctx(user), draft.id, ConfirmIn(version=1))


def test_other_user_cannot_touch_draft(db):
    seed_dicts(db)
    owner = make_user(db, "fu_svc_g1")
    other = make_user(db, "fu_svc_g2")
    draft, _ = followup_service.create_draft(db, _ctx(owner), DraftCreateIn(request_id="req-draft-g", raw_text="x"))
    with pytest.raises(LookupError):
        followup_service.get_draft(db, _ctx(other), draft.id)
    with pytest.raises(LookupError):
        followup_service.discard_draft(db, _ctx(other), draft.id)


def test_stale_running_draft_is_marked_failed(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_l")
    draft, _ = followup_service.create_draft(db, _ctx(user), DraftCreateIn(request_id="req-draft-l", raw_text="x"))
    draft.updated_at = datetime(2026, 10, 30, 8, 0)
    db.commit()
    import app.domestic_followup.followup_service as svc
    original = svc.beijing_now
    svc.beijing_now = lambda: datetime(2026, 10, 30, 8, 11)
    try:
        assert followup_service.get_draft(db, _ctx(user), draft.id)["ai_status"] == "failed"
    finally:
        svc.beijing_now = original


def test_quick_receipt_ok_closes_receipt_task(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_h")
    customer = make_customer(db, user, "服务店H")
    task = DomesticFollowupTask(task_type="receipt", customer_id=customer.id, assignee_user_id=user.id,
                                source_key="receipt:h", title="收货回访", due_date=TODAY)
    db.add(task)
    db.commit()
    followup = followup_service.quick_receipt_ok(db, _ctx(user), task.id, "req-receipt-h")
    assert followup.raw_text == "已回访，客户无问题反馈" and followup.status == "confirmed"
    db.refresh(task)
    assert task.status == "done" and task.closed_reason == "回访完成"
    assert followup_service.quick_receipt_ok(db, _ctx(user), task.id, "req-receipt-h").id == followup.id


def test_resolved_item_must_belong_to_same_customer(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_i")
    c1 = make_customer(db, user, "服务店I1")
    c2 = make_customer(db, user, "服务店I2")
    first, _ = followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        request_id="req-direct-i1", customer_id=c1.id, raw_text="x",
        items=[{"kind": "issue", "text": "掉发", "category": "质量"}]))
    item = db.query(DomesticFollowupItem).filter_by(followup_id=first.id).one()
    with pytest.raises(ValueError, match="不属于该客户"):
        followup_service.direct_save(db, _ctx(user), DirectSaveIn(
            request_id="req-direct-i2", customer_id=c2.id, raw_text="y",
            resolved_items=[{"item_id": item.id, "resolution": "已换货"}]))


def test_timeline_on_public_sea_hides_other_authors(db):
    seed_dicts(db)
    a = make_user(db, "fu_svc_k1")
    b = make_user(db, "fu_svc_k2")
    customer = make_customer(db, None, "公海店K", creator=a)
    followup_service.direct_save(db, _ctx(a), DirectSaveIn(
        request_id="req-direct-k", customer_id=customer.id, raw_text="A 的私下沟通",
        items=[{"kind": "issue", "text": "掉色", "category": "质量"}]))
    seen_by_b = followup_service.timeline(db, _ctx(b), customer.id)
    assert seen_by_b["customer"]["writable"] is True and seen_by_b["customer"]["readable"] is False
    assert seen_by_b["events"] == [] and seen_by_b["open_items"] == []


def test_timeline_merges_followups_and_shipments(db):
    seed_dicts(db)
    user = make_user(db, "fu_svc_j")
    customer = make_customer(db, user, "服务店J")
    make_shipment(db, customer, user, datetime(2026, 10, 27, 10, 0))
    followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        request_id="req-direct-j", customer_id=customer.id, raw_text="回访", followup_date=date(2026, 10, 29)))
    timeline = followup_service.timeline(db, _ctx(user), customer.id)
    assert [e["type"] for e in timeline["events"]] == ["followup", "shipment"]
    assert timeline["events"][1]["data"]["quantity"] == 2
    assert timeline["customer"]["days_since_followup"] == 1
    assert timeline["customer"]["frequency_days"] == 30  # B级 默认 30 天
