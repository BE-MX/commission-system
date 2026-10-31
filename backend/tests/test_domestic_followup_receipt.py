from contextlib import contextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import event

from app.domestic_followup import config_service, receipt_service
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupTask, DomesticFollowupTaskShipment
from tests.domestic_followup_helpers import make_customer, make_shipment, make_user

TODAY = date(2026, 10, 30)


def _launch(db, value="2026-10-01"):
    config_service.update_config(db, {"receipt_launch_date": value}, None, commit=False)


def test_first_scan_sets_launch_date_and_skips_history(db):
    user = make_user(db, "fu_rc_a")
    customer = make_customer(db, user, "回访店A")
    make_shipment(db, customer, user, datetime(2026, 10, 20, 9, 0))
    assert receipt_service.scan(db, today=TODAY) == 0
    assert config_service.get_config(db)["receipt_launch_date"] == "2026-10-30"


def test_groups_same_customer_same_day_and_respects_beijing_day_boundary(db):
    user = make_user(db, "fu_rc_b")
    customer = make_customer(db, user, "回访店B")
    _launch(db)
    s1 = make_shipment(db, customer, user, datetime(2026, 10, 27, 0, 0), quantity=2)
    s2 = make_shipment(db, customer, user, datetime(2026, 10, 27, 23, 59), quantity=3)
    make_shipment(db, customer, user, datetime(2026, 10, 28, 0, 0))  # 第 2 天，未到 3 天
    make_shipment(db, customer, user, datetime(2026, 10, 26, 8, 0), cancelled=True)

    assert receipt_service.scan(db, today=TODAY) == 1
    task = db.query(DomesticFollowupTask).one()
    assert task.task_type == "receipt" and task.due_date == TODAY and task.assignee_user_id == user.id
    assert task.source_key == f"receipt:{customer.id}:2026-10-27:{min(s1.id, s2.id)}"
    assert [s["quantity"] for s in task.payload["shipments"]] == [2, 3]
    assert "2 批 5 件" in task.title
    assert receipt_service.scan(db, today=TODAY) == 0  # 幂等


def test_public_sea_customer_falls_back_to_shipment_creator(db):
    clerk = make_user(db, "fu_rc_c")
    customer = make_customer(db, None, "公海店C", creator=clerk)
    _launch(db)
    make_shipment(db, customer, clerk, datetime(2026, 10, 26, 10, 0))
    receipt_service.scan(db, today=TODAY)
    assert db.query(DomesticFollowupTask).one().assignee_user_id == clerk.id


def test_late_batch_on_same_day_creates_separate_task(db):
    user = make_user(db, "fu_rc_d")
    customer = make_customer(db, user, "回访店D")
    _launch(db)
    make_shipment(db, customer, user, datetime(2026, 10, 27, 9, 0))
    receipt_service.scan(db, today=TODAY)
    make_shipment(db, customer, user, datetime(2026, 10, 27, 18, 0))  # 补录
    assert receipt_service.scan(db, today=TODAY) == 1
    assert db.query(DomesticFollowupTaskShipment).count() == 2


def test_scan_defaults_to_beijing_today(db, monkeypatch):
    user = make_user(db, "fu_rc_e")
    customer = make_customer(db, user, "回访店E")
    _launch(db)
    make_shipment(db, customer, user, datetime(2026, 10, 27, 9, 0))
    monkeypatch.setattr(receipt_service, "beijing_today", lambda: TODAY)  # 服务器非东八区时也只认北京日
    assert receipt_service.scan(db) == 1


def test_expire_receipt_tasks_after_seven_days(db):
    user = make_user(db, "fu_rc_f")
    customer = make_customer(db, user, "回访店F")
    for key, kind, due in (("old", "receipt", TODAY - timedelta(days=8)), ("edge", "receipt", TODAY - timedelta(days=7)),
                           ("plan", "plan", TODAY - timedelta(days=30))):
        db.add(DomesticFollowupTask(task_type=kind, customer_id=customer.id, assignee_user_id=user.id,
                                    source_key=key, title=key, due_date=due))
    db.flush()
    assert receipt_service.expire_tasks(db, today=TODAY) == 1
    statuses = {t.source_key: (t.status, t.closed_reason) for t in db.query(DomesticFollowupTask).all()}
    assert statuses == {"old": ("expired", "超时过期"), "edge": ("todo", None), "plan": ("todo", None)}


def test_cleanup_stale_drafts(db):
    user = make_user(db, "fu_rc_g")
    old = DomesticFollowup(author_user_id=user.id, followup_date=TODAY, request_id="rc-old", status="draft",
                           created_at=datetime(2026, 10, 22, 9, 0), version=1)
    fresh = DomesticFollowup(author_user_id=user.id, followup_date=TODAY, request_id="rc-new", status="draft",
                             created_at=datetime(2026, 10, 29, 9, 0), version=1)
    db.add_all([old, fresh])
    db.flush()
    assert receipt_service.cleanup_drafts(db, now=datetime(2026, 10, 30, 2, 10)) == 1
    assert old.status == "discarded" and old.version == 2 and fresh.status == "draft"


def test_inactive_owner_falls_back_to_creator_then_fallback(db):
    owner = make_user(db, "fu_rc_h1")
    clerk = make_user(db, "fu_rc_h2")
    backup = make_user(db, "fu_rc_h3")
    _launch(db)
    config_service.update_config(db, {"fallback_assignee_user_id": backup.id}, None, commit=False)
    c1 = make_customer(db, owner, "回访店H1")
    c2 = make_customer(db, owner, "回访店H2")
    make_shipment(db, c1, clerk, datetime(2026, 10, 26, 9, 0))
    make_shipment(db, c2, owner, datetime(2026, 10, 26, 9, 0))
    owner.is_active = False
    db.flush()
    assert receipt_service.scan(db, today=TODAY) == 2
    assignees = {t.customer_id: t.assignee_user_id for t in db.query(DomesticFollowupTask).all()}
    assert assignees == {c1.id: clerk.id, c2.id: backup.id}


def test_no_active_assignee_skips_group(db):
    owner = make_user(db, "fu_rc_i")
    customer = make_customer(db, owner, "回访店I")
    _launch(db)
    make_shipment(db, customer, owner, datetime(2026, 10, 26, 9, 0))
    owner.is_active = False
    db.flush()
    assert receipt_service.scan(db, today=TODAY) == 0
    assert db.query(DomesticFollowupTask).count() == 0 and db.query(DomesticFollowupTaskShipment).count() == 0


def test_batches_beyond_expire_window_are_not_backfilled(db):
    user = make_user(db, "fu_rc_j")
    customer = make_customer(db, user, "回访店J")
    _launch(db, "2026-09-01")
    make_shipment(db, customer, user, datetime(2026, 10, 19, 23, 59))  # 10-19 + 3 = 10-22，已过 7 天过期窗口
    kept = make_shipment(db, customer, user, datetime(2026, 10, 20, 0, 0))  # 10-23 到期，正好在窗口内
    assert receipt_service.scan(db, today=TODAY) == 1
    assert [link.shipment_id for link in db.query(DomesticFollowupTaskShipment).all()] == [kept.id]


@contextmanager
def _concurrent_write_before_update(db, table, sql):
    """在本模块发出第一条 UPDATE <table> 之前，模拟另一事务已提交的写入。"""
    engine = db.get_bind()
    fired = []

    def hook(conn, cursor, statement, parameters, context, executemany):
        if not fired and statement.lstrip().upper().startswith(f"UPDATE {table.upper()}"):
            fired.append(True)
            cursor.execute(sql)

    event.listen(engine, "before_cursor_execute", hook)
    try:
        yield fired
    finally:
        event.remove(engine, "before_cursor_execute", hook)


def test_expire_does_not_overwrite_task_finished_concurrently(db):
    user = make_user(db, "fu_rc_k")
    customer = make_customer(db, user, "回访店K")
    task = DomesticFollowupTask(task_type="receipt", customer_id=customer.id, assignee_user_id=user.id,
                                source_key="race", title="race", due_date=TODAY - timedelta(days=10))
    db.add(task)
    db.flush()
    with _concurrent_write_before_update(
            db, "ark_domestic_followup_tasks",
            f"UPDATE ark_domestic_followup_tasks SET status='done', closed_reason='回访完成' WHERE id={task.id}") as fired:
        receipt_service.expire_tasks(db, today=TODAY)
    db.expire_all()
    assert fired and db.get(DomesticFollowupTask, task.id).status == "done"


def test_cleanup_does_not_discard_draft_confirmed_concurrently(db):
    user = make_user(db, "fu_rc_l")
    draft = DomesticFollowup(author_user_id=user.id, followup_date=TODAY, request_id="rc-race", status="draft",
                             created_at=datetime(2026, 10, 20, 9, 0), version=1)
    db.add(draft)
    db.flush()
    with _concurrent_write_before_update(
            db, "ark_domestic_followups",
            f"UPDATE ark_domestic_followups SET status='confirmed', version=2 WHERE id={draft.id}") as fired:
        receipt_service.cleanup_drafts(db, now=datetime(2026, 10, 30, 2, 10))
    db.expire_all()
    assert fired and db.get(DomesticFollowup, draft.id).status == "confirmed"
