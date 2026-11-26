"""Deleting a todo preserves its source and closes only the task."""
from datetime import date

import pytest
from sqlalchemy import event, update

from app.domestic_followup import task_service
from app.domestic_followup.collaboration_models import FollowupResponsibility
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem
from tests.domestic_followup_helpers import followup_client, make_customer, make_user

DAY = date(2026, 11, 26)


def setup_task(db, kind="plan", purpose=None):
    owner = make_user(db, "delete-owner")
    customer = make_customer(db, owner, "删除待办测试")
    source = DomesticFollowup(author_user_id=owner.id, customer_id=customer.id,
                              followup_date=DAY, request_id="delete-source", status="confirmed")
    db.add(source)
    db.flush()
    item = None
    if kind in ("issue", "suggestion"):
        item = DomesticFollowupItem(followup_id=source.id, customer_id=customer.id, seq=1,
                                    kind=kind, text="保留记录", status="open", handler_user_id=owner.id)
        db.add(item)
        db.flush()
    task, _ = task_service.upsert_task(
        db, source_key="delete-test", task_type=kind, customer_id=customer.id,
        assignee_user_id=owner.id, title="待办", due_date=DAY, purpose=purpose,
        source_followup_id=source.id, source_item_id=item.id if item else None)
    return owner, customer, source, item, task


@pytest.mark.parametrize("kind", ["plan", "receipt", "issue", "suggestion"])
def test_delete_persists_audit_preserves_source_and_is_idempotent(db, kind):
    owner, _, source, item, task = setup_task(db, kind)
    with followup_client(db, owner) as client:
        response = client.delete(f"/api/domestic-followup/tasks/{task.id}")
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"id": task.id, "status": "cancelled"}
        closed_at = task.closed_at
        assert client.delete(f"/api/domestic-followup/tasks/{task.id}").status_code == 200
        assert client.get("/api/domestic-followup/tasks").json()["data"]["total"] == 0
        assert all(value == 0 for value in client.get("/api/domestic-followup/tasks/summary").json()["data"].values())
    db.expire_all()
    assert task.closed_by_user_id == owner.id and task.closed_at == closed_at
    assert task.closed_reason == task_service.CLOSE_TASK_DELETED
    assert source.status == "confirmed" and task.source_followup_id == source.id
    if item:
        assert item.status == "open" and task.source_item_id == item.id
    replay, created = task_service.upsert_task(
        db, source_key=task.source_key, task_type=kind, customer_id=task.customer_id,
        assignee_user_id=owner.id, title="重试创建", due_date=DAY)
    assert not created and replay.id == task.id and replay.status == "cancelled"


def test_delete_checks_write_and_actor_and_missing_task(db):
    owner, customer, _, _, task = setup_task(db)
    other = make_user(db, "delete-outsider")
    db.add(FollowupResponsibility(customer_id=customer.id, owner_user_id=other.id, status="active"))
    db.flush()
    with followup_client(db, owner, permissions=("domestic_followup:read",)) as client:
        assert client.delete(f"/api/domestic-followup/tasks/{task.id}").status_code == 403
    # A managed customer's owner/read-all user cannot modify another assignee's todo.
    with followup_client(db, other, permissions=("domestic_followup:write", "domestic_followup:read_all")) as client:
        assert client.delete(f"/api/domestic-followup/tasks/{task.id}").status_code == 403
    with followup_client(db, owner) as client:
        assert client.delete("/api/domestic-followup/tasks/999999").status_code == 404
    assert task.status == "todo"


@pytest.mark.parametrize("kind,status", [("action", "todo"), ("plan", "done"), ("receipt", "expired"), ("issue", "cancelled")])
def test_delete_cannot_bypass_action_reason_or_overwrite_finished_audit(db, kind, status):
    owner, _, _, _, task = setup_task(db, kind)
    task.status = status
    task.closed_reason = "原关闭原因" if status != "todo" else None
    db.flush()
    with followup_client(db, owner) as client:
        assert client.delete(f"/api/domestic-followup/tasks/{task.id}").status_code == 400
    assert task.status == status
    if status != "todo":
        assert task.closed_reason == "原关闭原因"


def test_delete_development_plan_updates_next_date_and_version_once(db):
    owner, customer, _, _, task = setup_task(db, purpose="development")
    responsibility = FollowupResponsibility(customer_id=customer.id, owner_user_id=owner.id,
                                            status="active", next_plan_date=DAY, version=3)
    db.add(responsibility)
    later, _ = task_service.upsert_task(
        db, source_key="delete-later", task_type="plan", purpose="development", customer_id=customer.id,
        assignee_user_id=owner.id, title="后续安排", due_date=date(2026, 12, 1))
    db.flush()
    with followup_client(db, owner) as client:
        assert client.delete(f"/api/domestic-followup/tasks/{task.id}").status_code == 200
        assert responsibility.next_plan_date == later.due_date and responsibility.version == 4
        assert client.delete(f"/api/domestic-followup/tasks/{task.id}").status_code == 200
        assert responsibility.version == 4
        assert client.delete(f"/api/domestic-followup/tasks/{later.id}").status_code == 200
        assert responsibility.next_plan_date is None and responsibility.version == 5


@pytest.mark.parametrize("operation", ["resolve", "transfer"])
def test_item_mutations_lock_current_tasks_and_preserve_deleted_audit(db, operation):
    from app.domestic_followup.models import DomesticFollowupTask
    from tests.domestic_followup_helpers import grant

    owner, _, _, item, task = setup_task(db, "issue")
    target = make_user(db, "delete-transfer-target")
    grant(db, target, "domestic_followup:write")
    # Simulate a stale ORM identity after another writer deleted the task.
    db.execute(update(DomesticFollowupTask).where(DomesticFollowupTask.id == task.id).values(
        status="cancelled", closed_reason=task_service.CLOSE_TASK_DELETED,
        closed_by_user_id=owner.id), execution_options={"synchronize_session": False})
    assert task.status == "todo"
    reads = []

    def check_current_read(state):
        if state.is_select and DomesticFollowupTask.__table__ in state.statement.get_final_froms():
            reads.append(state.statement)
            assert state.statement._for_update_arg is not None
            assert state.load_options._populate_existing

    event.listen(db, "do_orm_execute", check_current_read)
    try:
        actor = {"sub": str(owner.id), "permissions": ["domestic_followup:write"]}
        if operation == "resolve":
            task_service.resolve_item(db, actor, item.id, status="resolved", resolution="处理完成")
        else:
            task_service.transfer_item(db, actor, item.id, target.id)
    finally:
        event.remove(db, "do_orm_execute", check_current_read)
    assert reads
    db.refresh(task)
    assert task.status == "cancelled" and task.closed_reason == task_service.CLOSE_TASK_DELETED
    assert task.assignee_user_id == owner.id and task.closed_by_user_id == owner.id
