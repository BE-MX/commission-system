"""任务服务：创建/更新/树规则/隔离。状态机与回收站见 test_task_state.py。"""
import pytest

from app.task import module_service, service
from app.task.errors import TaskInvalid, TaskNotFound
from app.task.models import TaskEvent
from tests.task_helpers import make_user


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    return make_user(db, "svc_owner")


def chain(db, owner_id, depth):
    """建一条深度为 depth 的父子链，返回自顶向下的任务列表。"""
    tasks, parent = [], None
    for i in range(depth):
        t = service.create_task(db, owner_id, title=f"L{i + 1}", parent_id=parent)
        tasks.append(t)
        parent = t.id
    return tasks


def test_create_defaults_and_event(db, owner):
    t = service.create_task(db, owner.id, title="  写汇报  ", module_key="custom.report", source="nav_quick")
    assert t.title == "写汇报" and t.priority == "P2" and t.status == "todo" and t.source == "nav_quick"
    ev = db.query(TaskEvent).filter_by(task_id=t.id).one()
    assert ev.type == "created" and ev.actor == "user"


@pytest.mark.parametrize("bad", [{"title": ""}, {"title": "x" * 201}, {"title": "ok", "priority": "P9"},
                                 {"title": "ok", "module_key": "nope"}, {"title": "ok", "source": "hack"}])
def test_create_validation(db, owner, bad):
    with pytest.raises(TaskInvalid):
        service.create_task(db, owner.id, **bad)


def test_acceptance_is_cleaned(db, owner):
    t = service.create_task(db, owner.id, title="t", acceptance=["  a  ", "", "b", *["c"] * 10])
    assert t.acceptance == ["a", "b", "c", "c", "c", "c", "c", "c"]


def test_depth_limit_four(db, owner):
    tasks = chain(db, owner.id, 4)
    with pytest.raises(TaskInvalid, match="4 层"):
        service.create_task(db, owner.id, title="L5", parent_id=tasks[-1].id)


def test_parent_must_belong_to_owner(db, owner):
    other = make_user(db, "svc_other")
    foreign = service.create_task(db, other.id, title="别人的")
    with pytest.raises(TaskNotFound):
        service.create_task(db, owner.id, title="挂到别人下面", parent_id=foreign.id)


def test_get_task_isolated(db, owner):
    other = make_user(db, "svc_iso")
    t = service.create_task(db, owner.id, title="mine")
    with pytest.raises(TaskNotFound):
        service.get_task(db, other.id, t.id)


def test_update_whitelist_and_event(db, owner):
    t = service.create_task(db, owner.id, title="old")
    service.update_task(db, owner.id, t.id, {"title": "new", "priority": "P0", "due_date": "2026-10-01"})
    assert t.title == "new" and t.priority == "P0" and str(t.due_date) == "2026-10-01"
    with pytest.raises(TaskInvalid):
        service.update_task(db, owner.id, t.id, {"status": "done"})
    ev = db.query(TaskEvent).filter_by(task_id=t.id, type="updated").one()
    assert set(ev.payload_json["fields"]) == {"title", "priority", "due_date"}


def test_move_rejects_cycle_and_depth(db, owner):
    a, b, c = chain(db, owner.id, 3)
    with pytest.raises(TaskInvalid, match="子任务"):
        service.move_task(db, owner.id, a.id, c.id)
    with pytest.raises(TaskInvalid, match="子任务"):
        service.move_task(db, owner.id, a.id, a.id)
    d1, d2 = chain(db, owner.id, 2)
    with pytest.raises(TaskInvalid, match="4 层"):
        service.move_task(db, owner.id, a.id, d2.id)   # a 子树高 3 + d2 深度 2 = 5
    service.move_task(db, owner.id, c.id, None)
    assert c.parent_id is None


def test_list_tree_progress_counts_closed_leaves(db, owner):
    root = service.create_task(db, owner.id, title="root")
    k1 = service.create_task(db, owner.id, title="k1", parent_id=root.id)
    service.create_task(db, owner.id, title="k2", parent_id=root.id)
    service.create_task(db, owner.id, title="g1", parent_id=k1.id)
    done = service.create_task(db, owner.id, title="g2", parent_id=k1.id)
    service.change_status(db, owner.id, done.id, "done")
    tree = service.list_tree(db, owner.id)
    node = next(n for n in tree if n["id"] == root.id)
    assert node["progress"] == {"done": 1, "total": 3}
    assert [c["title"] for c in node["children"]] == ["k1", "k2"]
    assert node["code"] == f"T-{root.id}"
