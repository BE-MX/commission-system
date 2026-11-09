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
    make_shipment(db, customer, a, datetime(2026, 10, 27, 10, 0))  # 发货也是客户经营数据，不可读者不能看
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


def test_using_someone_elses_source_task_rejects_write(db):
    seed_dicts(db)
    owner = make_user(db, "fu_svc_m1")
    helper = make_user(db, "fu_svc_m2")
    customer = make_customer(db, owner, "服务店M")
    # 转交的异常只授权处理该异常，不能作为其他待办的写入凭据。
    db.add(DomesticFollowupTask(task_type="issue", customer_id=customer.id, assignee_user_id=helper.id,
                                source_key="item:m", title="异常", due_date=TODAY))
    receipt = DomesticFollowupTask(task_type="receipt", customer_id=customer.id, assignee_user_id=owner.id,
                                   source_key="receipt:m", title="回访", due_date=TODAY)
    db.add(receipt)
    db.commit()
    with pytest.raises(PermissionError, match="不是你的待办"):
        followup_service.direct_save(db, _ctx(helper), DirectSaveIn(
            request_id="req-direct-m", customer_id=customer.id, raw_text="帮忙问了下",
            source_task_id=receipt.id, close_task_ids=[receipt.id]))
    db.refresh(receipt)
    assert receipt.status == "todo"


def test_duplicate_request_race_returns_existing_record(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_svc_n")
    customer = make_customer(db, user, "服务店N")
    db.commit()
    payload = DirectSaveIn(request_id="req-direct-n", customer_id=customer.id, raw_text="x")
    first, _ = followup_service.direct_save(db, _ctx(user), payload)
    original = followup_service._by_request
    calls = []

    def racing(*args):  # 第一次预查没看到（并发双击），撞唯一键后的重查才看到
        calls.append(args)
        return None if len(calls) == 1 else original(*args)

    monkeypatch.setattr(followup_service, "_by_request", racing)
    again, pending = followup_service.direct_save(db, _ctx(user), payload)
    assert again.id == first.id and pending == []
    calls.clear()
    draft, created = followup_service.create_draft(db, _ctx(user), DraftCreateIn(request_id="req-direct-n", raw_text="x"))
    assert draft.id == first.id and created is False


def test_integrity_error_without_existing_record_is_not_reported_as_duplicate(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_svc_o")
    customer = make_customer(db, user, "服务店O")
    db.commit()
    payload = DirectSaveIn(request_id="req-direct-o", customer_id=customer.id, raw_text="x")
    followup_service.direct_save(db, _ctx(user), payload)
    monkeypatch.setattr(followup_service, "_by_request", lambda *a: None)
    with pytest.raises(ValueError, match="保存失败，请重试"):
        followup_service.direct_save(db, _ctx(user), payload)


def _receipt_task(db, user, customer, key):
    task = DomesticFollowupTask(task_type="receipt", customer_id=customer.id, assignee_user_id=user.id,
                                source_key=key, title="收货回访", due_date=TODAY)
    db.add(task)
    db.commit()
    return task


def _racing_by_request(monkeypatch):
    original = followup_service._by_request
    calls = []

    def racing(*args):  # 第一次预查没看到（并发双击），之后的重查才看到
        calls.append(args)
        return None if len(calls) == 1 else original(*args)

    monkeypatch.setattr(followup_service, "_by_request", racing)


def test_quick_receipt_ok_request_id_collision_returns_existing(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_svc_r1")
    customer = make_customer(db, user, "服务店R1")
    task = _receipt_task(db, user, customer, "receipt:r1")
    first = followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        request_id="req-receipt-r1", customer_id=customer.id, raw_text="x"))[0]
    _racing_by_request(monkeypatch)
    again = followup_service.quick_receipt_ok(db, _ctx(user), task.id, "req-receipt-r1")
    assert again.id == first.id
    db.refresh(task)
    assert task.status == "todo"  # 撞键那次整体回滚，不留半截


def test_quick_receipt_ok_double_click_after_task_closed_returns_existing(db, monkeypatch):
    seed_dicts(db)
    user = make_user(db, "fu_svc_r2")
    customer = make_customer(db, user, "服务店R2")
    task = _receipt_task(db, user, customer, "receipt:r2")
    first = followup_service.quick_receipt_ok(db, _ctx(user), task.id, "req-receipt-r2")
    _racing_by_request(monkeypatch)
    # 第二次点击等锁时第一次已提交：任务已结束，但同一 request_id 的记录在，应返回它而不是报冲突
    assert followup_service.quick_receipt_ok(db, _ctx(user), task.id, "req-receipt-r2").id == first.id
