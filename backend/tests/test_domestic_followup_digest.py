import asyncio
from datetime import date, datetime
from unittest.mock import Mock

from app.domestic_followup import config_service, digest_service
from app.domestic_followup.models import (
    DomesticFollowupConfig, DomesticFollowup, DomesticFollowupDigest, DomesticFollowupItem, DomesticFollowupTask,
)
from tests.domestic_followup_helpers import grant, make_customer, make_user

TODAY = date(2026, 10, 30)


def _task(db, user, customer, key, kind, due, severity=None):
    db.add(DomesticFollowupTask(task_type=kind, customer_id=customer.id, assignee_user_id=user.id, source_key=key,
                                title=f"{customer.shop_name}：{key}", due_date=due,
                                payload={"severity": severity} if severity else None))


def test_build_daily_groups_by_assignee_and_is_idempotent(db):
    a = make_user(db, "fu_dg_a", dingtalk_id="dt-a")
    b = make_user(db, "fu_dg_b", dingtalk_id="dt-b")
    ca = make_customer(db, a, "推送店A")
    cb = make_customer(db, b, "推送店B")
    _task(db, a, ca, "a1", "receipt", TODAY)
    _task(db, a, ca, "a2", "plan", date(2026, 10, 25))
    _task(db, a, ca, "a3", "issue", TODAY, severity="紧急")
    _task(db, a, ca, "a4", "plan", date(2026, 11, 3))  # 未来，不进汇总
    _task(db, b, cb, "b1", "plan", date(2026, 11, 3))  # b 今天没有到期 → 不推
    db.flush()

    assert digest_service.build_daily(db, TODAY) == 1
    assert digest_service.build_daily(db, TODAY) == 0
    digest = db.query(DomesticFollowupDigest).one()
    assert digest.user_id == a.id and digest.kind == "daily" and digest.ref_key == ""
    assert "收货回访 1" in digest.markdown and "约定跟进 1（逾期 1）" in digest.markdown
    assert "异常意见 1（紧急 1）" in digest.markdown and "/domestic/followups" in digest.markdown


def test_pending_skips_users_without_dingtalk(db):
    user = make_user(db, "fu_dg_c")
    customer = make_customer(db, user, "推送店C")
    _task(db, user, customer, "c1", "plan", TODAY)
    db.flush()
    digest_service.build_daily(db, TODAY)
    assert digest_service.pending(db, "daily", TODAY) == []
    digest = db.query(DomesticFollowupDigest).one()
    assert digest.attempts == 5 and digest.last_error == "接收人未绑定钉钉"


def test_enqueue_urgent_per_receiver_and_dedup(db):
    author = make_user(db, "fu_dg_d1")
    boss = make_user(db, "fu_dg_d2", dingtalk_id="dt-boss")
    grant(db, boss, "domestic_followup:read_all")
    customer = make_customer(db, author, "推送店D")
    config_service.update_config(db, {"urgent_receiver_user_ids": [boss.id]}, None, commit=False)
    followup = DomesticFollowup(author_user_id=author.id, customer_id=customer.id, followup_date=TODAY,
                                request_id="dg-d", status="confirmed", version=2)
    db.add(followup)
    db.flush()
    item = DomesticFollowupItem(followup_id=followup.id, customer_id=customer.id, seq=1, kind="issue",
                                text="整批掉发", category="质量", severity="紧急", status="open")
    db.add(item)
    db.flush()
    digest_service.enqueue_urgent(db, item, customer, followup, today=TODAY)
    digest_service.enqueue_urgent(db, item, customer, followup, today=TODAY)
    row = db.query(DomesticFollowupDigest).one()
    assert row.kind == "urgent" and row.ref_key == f"item:{item.id}" and row.user_id == boss.id
    assert "整批掉发" in row.markdown and "推送店D" in row.title

    pushes = digest_service.pending(db, "urgent", TODAY)
    assert pushes == [{"digest_id": row.id, "dingtalk_id": "dt-boss", "title": row.title, "markdown": row.markdown}]


def test_mark_results_and_retry_cap(db):
    user = make_user(db, "fu_dg_e", dingtalk_id="dt-e")
    rows = [DomesticFollowupDigest(user_id=user.id, digest_date=TODAY, kind="urgent", ref_key=f"item:{i}",
                                   title="t", markdown="m", attempts=4 if i == 2 else 0) for i in (1, 2)]
    db.add_all(rows)
    db.flush()
    digest_service.mark(db, ok_ids=[rows[0].id], failed_ids=[rows[1].id])
    assert rows[0].pushed_at is not None
    assert rows[1].attempts == 5 and rows[1].last_error == "钉钉发送失败"
    assert digest_service.pending(db, "urgent", TODAY) == []


def test_send_uses_work_notifier(monkeypatch):
    notifier = Mock()

    async def fake_send(**kwargs):
        return kwargs["user_ids"] == ["dt-ok"]

    notifier.send_to_users = fake_send
    monkeypatch.setattr("app.dingtalk.work_notify.get_work_notifier", lambda: notifier)
    async def identity_claim(message):
        return message
    ok_ids, failed = asyncio.run(digest_service.send([
        {"digest_id": 1, "dingtalk_id": "dt-ok", "title": "t", "markdown": "m"},
        {"digest_id": 2, "dingtalk_id": "dt-bad", "title": "t", "markdown": "m"},
    ], identity_claim))
    assert ok_ids == [1] and failed == [2]


def test_jobs_registered(monkeypatch):
    from app.schedulers import registry

    scheduler = Mock()
    registry._register_jobs(scheduler, outbound_mode="legacy")
    calls = {call.kwargs["id"]: call for call in scheduler.add_job.call_args_list}
    daily = calls["domestic_followup_daily"].kwargs
    assert (daily["hour"], daily["minute"], daily["day_of_week"]) == (9, 0, "mon-sat")
    assert daily["timezone"] == "Asia/Shanghai"
    assert calls["domestic_followup_daily_retry_05"].kwargs["minute"] == 5
    assert calls["domestic_followup_daily_retry_15"].kwargs["minute"] == 15
    assert calls["domestic_followup_urgent"].kwargs["seconds"] == 60
    assert calls["domestic_followup_maintenance"].kwargs["hour"] == 2


def test_inactive_or_deleted_users_get_no_digest(db):
    gone = make_user(db, "fu_dg_f1", dingtalk_id="dt-f1")
    removed = make_user(db, "fu_dg_f2", dingtalk_id="dt-f2")
    customer = make_customer(db, gone, "推送店F")
    _task(db, gone, customer, "f1", "plan", TODAY)
    _task(db, removed, customer, "f2", "plan", TODAY)
    db.add(DomesticFollowupDigest(user_id=removed.id, digest_date=TODAY, kind="urgent", ref_key="item:1",
                                  title="t", markdown="m"))
    gone.is_active = False
    removed.deleted_at = datetime(2026, 10, 29, 9, 0)
    db.flush()
    assert digest_service.build_daily(db, TODAY) == 0
    assert digest_service.pending(db, "urgent", TODAY) == []


def test_enqueue_urgent_skips_missing_and_inactive_receivers(db):
    author = make_user(db, "fu_dg_g1")
    boss = make_user(db, "fu_dg_g2", dingtalk_id="dt-g2")
    left = make_user(db, "fu_dg_g3", dingtalk_id="dt-g3")
    left.is_active = False
    customer = make_customer(db, author, "推送店G")
    # 配置时都合规，事后有人离职或账号被删：直接写配置行模拟这种存量脏数据
    db.add(DomesticFollowupConfig(key="urgent_receiver_user_ids", value=[999999, left.id, boss.id]))
    db.flush()
    followup = DomesticFollowup(author_user_id=author.id, customer_id=customer.id, followup_date=TODAY,
                                request_id="dg-g", status="confirmed", version=2)
    db.add(followup)
    db.flush()
    item = DomesticFollowupItem(followup_id=followup.id, customer_id=customer.id, seq=1, kind="issue",
                                text="错发", category="发货物流", severity="紧急", status="open")
    db.add(item)
    db.flush()
    assert digest_service.enqueue_urgent(db, item, customer, followup, today=TODAY) == 1
    assert [r.user_id for r in db.query(DomesticFollowupDigest).all()] == [boss.id]


def test_failed_0900_push_is_picked_up_by_0905_retry(db):
    user = make_user(db, "fu_dg_h", dingtalk_id="dt-h")
    customer = make_customer(db, user, "推送店H")
    _task(db, user, customer, "h1", "plan", TODAY)
    db.flush()
    digest_service.build_daily(db, TODAY)
    first = digest_service.pending(db, "daily", TODAY)
    digest_service.mark(db, ok_ids=[], failed_ids=[first[0]["digest_id"]])
    assert digest_service.build_daily(db, TODAY) == 0  # 09:05 不重复建
    retry = digest_service.pending(db, "daily", TODAY)
    assert [p["digest_id"] for p in retry] == [first[0]["digest_id"]]


def test_build_daily_logs_count_of_tasks_skipped_for_inactive_assignees(db, capsys):
    gone = make_user(db, "fu_dg_i1", dingtalk_id="dt-i1")
    here = make_user(db, "fu_dg_i2", dingtalk_id="dt-i2")
    customer = make_customer(db, here, "推送店I")
    _task(db, gone, customer, "i1", "plan", TODAY)
    _task(db, gone, customer, "i2", "receipt", TODAY)
    _task(db, gone, customer, "i3", "plan", date(2026, 11, 3))  # 未到期，不计入
    _task(db, here, customer, "i4", "plan", TODAY)
    gone.is_active = False
    db.flush()
    assert digest_service.build_daily(db, TODAY) == 1
    assert "skipped 2 due task(s) of inactive assignees" in capsys.readouterr().out
