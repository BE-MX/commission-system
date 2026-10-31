from datetime import date

import pytest

from app.domestic_followup import task_service
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask
from tests.domestic_followup_helpers import grant, make_customer, make_user

TODAY = date(2026, 10, 30)


def _ctx(user, perms=("domestic_followup:read", "domestic_followup:write")):
    return {"sub": str(user.id), "roles": [], "permissions": list(perms)}


def _followup(db, user, customer, request_id, **kw):
    row = DomesticFollowup(author_user_id=user.id, customer_id=customer.id, request_id=request_id,
                           followup_date=kw.pop("followup_date", TODAY), status="confirmed", **kw)
    db.add(row)
    db.flush()
    return row


def test_plan_task_is_idempotent_and_backfill_is_overdue(db):
    user = make_user(db, "fu_task_a")
    customer = make_customer(db, user, "任务店A")
    followup = _followup(db, user, customer, "t-a", next_date=date(2026, 10, 20), next_plan="问补货")
    first = task_service.create_plan_task(db, followup, customer.shop_name)
    again = task_service.create_plan_task(db, followup, customer.shop_name)
    assert first.id == again.id
    assert first.due_date == date(2026, 10, 20) and first.assignee_user_id == user.id
    assert first.title == "任务店A：问补货"
    page = task_service.list_tasks(db, _ctx(user), today=TODAY)
    assert page["items"][0]["overdue_days"] == 10


def test_no_next_date_no_task(db):
    user = make_user(db, "fu_task_b")
    customer = make_customer(db, user, "任务店B")
    followup = _followup(db, user, customer, "t-b")
    assert task_service.create_plan_task(db, followup, customer.shop_name) is None


def test_snooze_moves_from_later_of_today_and_due(db):
    user = make_user(db, "fu_task_c")
    customer = make_customer(db, user, "任务店C")
    followup = _followup(db, user, customer, "t-c", next_date=date(2026, 10, 20))
    task = task_service.create_plan_task(db, followup, customer.shop_name)
    task_service.snooze(db, _ctx(user), task.id, days=1, today=TODAY)
    assert task.due_date == date(2026, 10, 31) and task.snooze_count == 1
    with pytest.raises(ValueError):
        task_service.snooze(db, _ctx(user), task.id, days=8, today=TODAY)


def test_snooze_rejects_other_users(db):
    owner = make_user(db, "fu_task_d1")
    other = make_user(db, "fu_task_d2")
    customer = make_customer(db, owner, "任务店D")
    followup = _followup(db, owner, customer, "t-d", next_date=date(2026, 11, 2))
    task = task_service.create_plan_task(db, followup, customer.shop_name)
    with pytest.raises(PermissionError):
        task_service.snooze(db, _ctx(other), task.id, days=1, today=TODAY)


def test_item_task_transfer_and_resolve(db):
    author = make_user(db, "fu_task_e1")
    qc = make_user(db, "fu_task_e2")
    customer = make_customer(db, author, "任务店E")
    followup = _followup(db, author, customer, "t-e")
    item = DomesticFollowupItem(followup_id=followup.id, customer_id=customer.id, seq=1, kind="issue",
                                text="色差明显", category="色差", severity="一般", status="open",
                                handler_user_id=author.id)
    db.add(item)
    db.flush()
    task = task_service.create_item_task(db, item, followup, customer.shop_name)
    assert task.task_type == "issue" and task.due_date == TODAY
    grant(db, qc, "domestic_followup:write")

    task_service.transfer_item(db, _ctx(author), item.id, qc.id, note="转质检")
    assert item.status == "handling" and item.handler_user_id == qc.id
    assert task.assignee_user_id == qc.id

    task_service.resolve_item(db, _ctx(qc), item.id, status="resolved", resolution="已补发")
    assert item.status == "resolved" and item.resolution == "已补发"
    assert task.status == "done" and task.closed_reason == "条目已解决"
    with pytest.raises(ValueError):
        task_service.resolve_item(db, _ctx(qc), item.id, status="resolved", resolution="again")


def test_close_tasks_for_followup_only_closes_same_customer_open_plan_and_receipt(db):
    user = make_user(db, "fu_task_f")
    c1 = make_customer(db, user, "任务店F1")
    c2 = make_customer(db, user, "任务店F2")
    t1 = task_service.create_plan_task(db, _followup(db, user, c1, "t-f1", next_date=TODAY), c1.shop_name)
    t2 = task_service.create_plan_task(db, _followup(db, user, c2, "t-f2", next_date=TODAY), c2.shop_name)
    receipt = DomesticFollowupTask(task_type="receipt", customer_id=c1.id, assignee_user_id=user.id,
                                   source_key="receipt:x", title="回访", due_date=TODAY)
    db.add(receipt)
    db.flush()
    closed = task_service.close_tasks_for_followup(db, _ctx(user), c1.id, [t1.id, t2.id, receipt.id], followup_id=999)
    assert set(closed) == {t1.id, receipt.id}
    assert t1.closed_reason == "有新跟进" and receipt.closed_reason == "回访完成"
    assert t2.status == "todo"


def test_summary_counts_due_and_urgent(db):
    user = make_user(db, "fu_task_g")
    customer = make_customer(db, user, "任务店G")
    rows = (("a", "receipt", None, TODAY), ("b", "plan", None, TODAY), ("c", "issue", "紧急", TODAY),
            ("d", "suggestion", "一般", TODAY), ("e", "plan", None, date(2026, 11, 5)))
    for key, kind, severity, due in rows:
        db.add(DomesticFollowupTask(task_type=kind, customer_id=customer.id, assignee_user_id=user.id,
                                    source_key=f"s:{key}", title=key, due_date=due,
                                    payload={"severity": severity} if severity else None))
    db.flush()
    summary = task_service.summary(db, _ctx(user), today=TODAY)
    assert summary == {"receipt": 1, "plan": 1, "issue": 2, "urgent": 1, "upcoming": 1}


def test_close_tasks_skips_tasks_the_actor_does_not_own(db):
    owner = make_user(db, "fu_task_h1")
    helper = make_user(db, "fu_task_h2")
    customer = make_customer(db, owner, "任务店H")
    # helper 只因手上有一张转交来的异常待办而能写这个客户
    db.add(DomesticFollowupTask(task_type="issue", customer_id=customer.id, assignee_user_id=helper.id,
                                source_key="item:h", title="异常", due_date=TODAY))
    receipt = DomesticFollowupTask(task_type="receipt", customer_id=customer.id, assignee_user_id=owner.id,
                                   source_key="receipt:h", title="回访", due_date=TODAY)
    db.add(receipt)
    db.flush()
    assert task_service.close_tasks_for_followup(db, _ctx(helper), customer.id, [receipt.id], followup_id=1) == []
    assert receipt.status == "todo"


def test_upsert_task_reraises_integrity_error_not_caused_by_duplicate_key(db):
    from sqlalchemy.exc import IntegrityError

    user = make_user(db, "fu_task_i")
    with pytest.raises(IntegrityError):
        task_service.upsert_task(db, source_key="plan:none", task_type="plan", customer_id=None,
                                 assignee_user_id=user.id, title="t", due_date=TODAY)


def _open_item(db, author, name, request_id):
    customer = make_customer(db, author, name)
    followup = _followup(db, author, customer, request_id)
    item = DomesticFollowupItem(followup_id=followup.id, customer_id=customer.id, seq=1, kind="issue",
                                text="掉色", category="色差", severity="一般", status="open",
                                handler_user_id=author.id)
    db.add(item)
    db.flush()
    return item


def test_transfer_rejects_receiver_without_followup_write(db):
    author = make_user(db, "fu_task_p1")
    reader = make_user(db, "fu_task_p2")
    grant(db, reader, "domestic_followup:read")
    item = _open_item(db, author, "任务店P", "t-p")
    with pytest.raises(ValueError, match="对方没有客户跟进权限，请先在角色管理中分配"):
        task_service.transfer_item(db, _ctx(author), item.id, reader.id)
    assert item.handler_user_id == author.id and item.status == "open"


def test_transfer_accepts_super_admin_receiver(db):
    author = make_user(db, "fu_task_q1")
    boss = make_user(db, "fu_task_q2")
    grant(db, boss, role_name="super_admin")
    item = _open_item(db, author, "任务店Q", "t-q")
    task_service.transfer_item(db, _ctx(author), item.id, boss.id)
    assert item.handler_user_id == boss.id


def test_search_users_only_returns_active_users_with_followup_write(db):
    writer = make_user(db, "fu_su_writer")
    reader = make_user(db, "fu_su_reader")
    boss = make_user(db, "fu_su_boss")
    gone = make_user(db, "fu_su_gone")
    grant(db, writer, "domestic_followup:write", "domestic_followup:read")
    grant(db, reader, "domestic_followup:read")
    grant(db, boss, role_name="super_admin")
    grant(db, gone, "domestic_followup:write")
    gone.is_active = False
    db.flush()
    names = [r["real_name"] for r in task_service.search_users(db, "fu_su")]
    assert names == ["fu_su_boss", "fu_su_writer"]
