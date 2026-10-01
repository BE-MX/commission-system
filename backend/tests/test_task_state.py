"""状态迁移矩阵、子任务未结束确认、回收站、关联、统计（含北京时间跨日）。"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.task import module_service, service
from app.task.errors import TaskConflict, TaskInvalid, TaskNotFound
from app.task.models import TaskEvent, TaskItem
from tests.task_helpers import make_user


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    return make_user(db, "state_owner")


@pytest.mark.parametrize("frm,to,ok", [
    ("todo", "in_progress", True), ("in_progress", "blocked", True), ("blocked", "todo", True),
    ("todo", "done", True), ("todo", "shelved", True),
    ("todo", "pending_confirm", False),          # 待确认只能由 AI/MCP 提议
    ("pending_confirm", "done", True), ("pending_confirm", "in_progress", True),
    ("pending_confirm", "todo", False), ("pending_confirm", "blocked", False), ("pending_confirm", "shelved", False),
    ("done", "todo", True), ("done", "in_progress", False), ("shelved", "done", False),
])
def test_user_transition_matrix(frm, to, ok):
    assert service.can_transition("user", frm, to) is ok


def test_ai_can_only_propose():
    assert service.can_transition("ai", "in_progress", "pending_confirm") is True
    assert service.can_transition("ai", "pending_confirm", "done") is False
    assert service.can_transition("reporter", "todo", "done") is False


def test_blocked_requires_reason_and_clears_on_leave(db, owner):
    t = service.create_task(db, owner.id, title="t")
    with pytest.raises(TaskInvalid, match="原因"):
        service.change_status(db, owner.id, t.id, "blocked")
    service.change_status(db, owner.id, t.id, "blocked", reason="等财务口径")
    assert t.blocked_reason == "等财务口径"
    service.change_status(db, owner.id, t.id, "in_progress")
    assert t.blocked_reason is None


def test_user_cannot_set_pending_confirm(db, owner):
    t = service.create_task(db, owner.id, title="t")
    with pytest.raises(TaskConflict):
        service.change_status(db, owner.id, t.id, "pending_confirm")


def test_reject_proposal_requires_reason(db, owner):
    task = service.create_task(db, owner.id, title="proposal")
    service.change_status(db, owner.id, task.id, "pending_confirm", actor="ai")
    with pytest.raises(TaskInvalid, match="驳回"):
        service.change_status(db, owner.id, task.id, "in_progress")
    service.change_status(db, owner.id, task.id, "in_progress", reason="验收项未完成")
    event = db.query(TaskEvent).filter_by(task_id=task.id, type="status_changed").order_by(TaskEvent.id.desc()).first()
    assert event.payload_json["reason"] == "验收项未完成"


def test_done_with_open_children_needs_confirmation(db, owner):
    parent = service.create_task(db, owner.id, title="p")
    service.create_task(db, owner.id, title="c", parent_id=parent.id)
    with pytest.raises(TaskConflict) as exc:
        service.change_status(db, owner.id, parent.id, "done")
    assert exc.value.code == "open_children" and exc.value.extra == {"open_children": 1}
    service.change_status(db, owner.id, parent.id, "done", confirm_open_children=True)
    assert parent.status == "done" and parent.completed_at is not None


def test_reopen_clears_completed_at_and_logs(db, owner):
    t = service.create_task(db, owner.id, title="t")
    service.change_status(db, owner.id, t.id, "done")
    service.change_status(db, owner.id, t.id, "todo")
    assert t.completed_at is None
    ev = db.query(TaskEvent).filter_by(task_id=t.id, type="status_changed").order_by(TaskEvent.id.desc()).first()
    assert ev.payload_json == {"from": "done", "to": "todo", "reason": None}


def test_soft_delete_subtree_and_restore(db, owner):
    root = service.create_task(db, owner.id, title="root")
    kid = service.create_task(db, owner.id, title="kid", parent_id=root.id)
    service.delete_task(db, owner.id, root.id)
    assert root.deleted_at is not None and kid.delete_batch == root.delete_batch
    with pytest.raises(TaskNotFound):
        service.get_task(db, owner.id, kid.id)
    assert [t["id"] for t in service.list_trash(db, owner.id)] == [root.id]
    service.restore_task(db, owner.id, root.id)
    assert root.deleted_at is None and kid.deleted_at is None


def test_restore_child_whose_parent_is_deleted_becomes_top_level(db, owner):
    root = service.create_task(db, owner.id, title="root")
    kid = service.create_task(db, owner.id, title="kid", parent_id=root.id)
    service.delete_task(db, owner.id, kid.id)
    service.delete_task(db, owner.id, root.id)
    service.restore_task(db, owner.id, kid.id)
    assert kid.parent_id is None and kid.deleted_at is None


def test_links_add_remove_and_dedupe(db, owner):
    t = service.create_task(db, owner.id, title="t")
    link = service.add_link(db, owner.id, t.id, kind="doc", ref="docs/a.md", title="设计")
    with pytest.raises(TaskConflict):
        service.add_link(db, owner.id, t.id, kind="doc", ref="docs/a.md", title="设计")
    with pytest.raises(TaskInvalid):
        service.add_link(db, owner.id, t.id, kind="branch", ref="x", title="")
    with pytest.raises(TaskInvalid):
        service.add_link(db, owner.id, t.id, kind="doc", ref="../secret.md", title="")
    service.remove_link(db, owner.id, link.id)
    assert service.task_detail(db, owner.id, t.id)["links"] == []


def test_stats_uses_beijing_date(db, owner):
    t = service.create_task(db, owner.id, title="逾期", due_date="2026-09-29", priority="P0")
    service.create_task(db, owner.id, title="today", due_date="2026-09-30")
    s = service.stats(db, owner.id, today=date(2026, 9, 30))
    assert s == {"in_progress": 0, "pending_confirm": 0, "p0_open": 1, "overdue": 1}
    service.change_status(db, owner.id, t.id, "done")
    assert service.stats(db, owner.id, today=date(2026, 9, 30))["overdue"] == 0


class _LosAngelesClock(datetime):
    """模拟服务器在 UTC-7：UTC 2026-09-29 16:30 = 北京 09-30 00:30 = 洛杉矶 09-29 09:30。"""
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 9, 29, 16, 30, tzinfo=timezone.utc)
        return base.astimezone(tz) if tz else (base - timedelta(hours=7)).replace(tzinfo=None)


def test_stats_default_today_crosses_midnight_on_non_beijing_server(db, owner, monkeypatch):
    monkeypatch.setattr("app.core.time.datetime", _LosAngelesClock)
    service.create_task(db, owner.id, title="昨天到期", due_date="2026-09-29")
    assert service.stats(db, owner.id)["overdue"] == 1   # 北京已是 09-30，09-29 到期即逾期


def test_restore_detaches_foreign_parent(db, owner):
    other = make_user(db, "restore_other")
    foreign_parent = service.create_task(db, other.id, title="other root")
    item = service.create_task(db, owner.id, title="mine")
    service.delete_task(db, owner.id, item.id)
    item.parent_id = foreign_parent.id  # simulate bad historical reference
    db.flush()
    restored = service.restore_task(db, owner.id, item.id)
    assert restored.parent_id is None
    assert [root["id"] for root in service.list_tree(db, owner.id)] == [item.id]
