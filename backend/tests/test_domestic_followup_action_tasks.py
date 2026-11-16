from datetime import date

import pytest

from app.domestic_followup import followup_service
from app.domestic_followup.models import DomesticFollowupTask
from app.domestic_followup.schemas import DirectSaveIn
from tests.domestic_followup_helpers import followup_client, grant, make_customer, make_user, seed_dicts

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(followup_service, "beijing_today", lambda: TODAY)
    monkeypatch.setattr(followup_service, "_enqueue_urgent", lambda *a, **k: None)


def _ctx(user):
    return {"sub": str(user.id), "roles": [], "permissions": ["domestic_followup:read", "domestic_followup:write"]}


def _steps():
    return [
        {"step_key": "primary", "text": "下周四回访方案", "due_date": "2026-11-05", "method": "微信",
         "basis": "customer_agreed", "trigger": "date", "is_primary": True},
        {"step_key": "technical", "text": "协调技术给方案", "due_date": "2026-11-03", "basis": "our_commitment",
         "trigger": "date", "done_criteria": "客户收到方案", "is_primary": False},
        {"step_key": "sample", "text": "寄出一顶样品", "due_date": "2026-11-04", "basis": "our_plan",
         "trigger": "date", "done_criteria": "录入快递单号", "is_primary": False},
    ]


def test_three_next_steps_create_one_plan_and_two_actions_idempotently(db):
    seed_dicts(db)
    user = make_user(db, "action_create")
    grant(db, user, "domestic_followup:write")
    customer = make_customer(db, user, "行动生成店")
    payload = DirectSaveIn(result_code="有效沟通", request_id="action-create-req", customer_id=customer.id,
                           raw_text="客户约定下周回访，我方协调技术并寄样", next_steps=_steps())
    record, _ = followup_service.direct_save(db, _ctx(user), payload)
    again, _ = followup_service.direct_save(db, _ctx(user), payload)
    assert again.id == record.id
    assert record.next_plan == "下周四回访方案" and record.next_date == date(2026, 11, 5)
    tasks = db.query(DomesticFollowupTask).filter_by(customer_id=customer.id).order_by(DomesticFollowupTask.id).all()
    assert [task.task_type for task in tasks] == ["action", "action", "plan"] or sorted(task.task_type for task in tasks) == ["action", "action", "plan"]
    actions = [task for task in tasks if task.task_type == "action"]
    assert len(actions) == 2
    assert {task.payload["step_key"] for task in actions} == {"technical", "sample"}
    assert all(task.purpose is None for task in actions)


def test_next_steps_require_exactly_one_primary_and_historical_rejects(db):
    seed_dicts(db)
    user = make_user(db, "action_primary")
    customer = make_customer(db, user, "主下一步店")
    steps = _steps()
    steps[0]["is_primary"] = False
    db.commit()
    with pytest.raises(ValueError, match="主下一步"):
        followup_service.direct_save(db, _ctx(user), DirectSaveIn(
            result_code="有效沟通", request_id="action-no-primary", customer_id=customer.id, raw_text="x", next_steps=steps))
    with pytest.raises(ValueError, match="历史补录"):
        followup_service.direct_save(db, _ctx(user), DirectSaveIn(
            result_code="有效沟通", request_id="action-history", customer_id=customer.id, raw_text="x",
            followup_date=date(2026, 10, 29), historical_only=True, next_steps=_steps()))


def test_action_complete_cancel_require_note_and_followup_does_not_auto_close(db):
    seed_dicts(db)
    user = make_user(db, "action_close")
    customer = make_customer(db, user, "行动关闭店")
    task = DomesticFollowupTask(task_type="action", customer_id=customer.id, assignee_user_id=user.id,
                                source_key="action:close:test", title="寄样", due_date=TODAY, payload={})
    db.add(task)
    db.commit()
    with followup_client(db, user) as client:
        assert client.post(f"/api/domestic-followup/tasks/{task.id}/complete", json={"note": " "}).status_code == 400
        completed = client.post(f"/api/domestic-followup/tasks/{task.id}/complete", json={"note": "已录入快递单号"})
        assert completed.status_code == 200, completed.text
    assert task.status == "done" and task.closed_reason == "已完成"
    assert task.payload["done_note"] == "已录入快递单号"
    record, _ = followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        result_code="有效沟通", request_id="action-not-autoclose", customer_id=customer.id, raw_text="新的沟通"))
    assert record.status == "confirmed" and task.status == "done"
    other = DomesticFollowupTask(task_type="action", customer_id=customer.id, assignee_user_id=user.id,
                                 source_key="action:close:other", title="核对方案", due_date=TODAY, payload={})
    db.add(other)
    db.commit()
    followup_service.direct_save(db, _ctx(user), DirectSaveIn(
        result_code="有效沟通", request_id="action-not-autoclose-2", customer_id=customer.id, raw_text="再次沟通"))
    assert other.status == "todo"
    with followup_client(db, user) as client:
        assert client.post(f"/api/domestic-followup/tasks/{other.id}/cancel", json={"reason": ""}).status_code == 400
        cancelled = client.post(f"/api/domestic-followup/tasks/{other.id}/cancel", json={"reason": "客户改为到店"})
        assert cancelled.status_code == 200
    assert other.status == "cancelled" and other.closed_reason == "已取消"
