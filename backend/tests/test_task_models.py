"""任务中心模型：建表、编号派生、唯一约束。"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.task.models import TaskBrief, TaskItem, TaskLink, TaskModule
from tests.task_helpers import make_user


def test_task_code_derives_from_id(db):
    owner = make_user(db, "tc_owner")
    db.add(TaskModule(key="custom.report", kind="custom", group_key="custom", group_title="方舟外", title="汇报材料"))
    task = TaskItem(owner_id=owner.id, title="写汇报", module_key="custom.report")
    db.add(task)
    db.flush()
    assert task.code == f"T-{task.id}"
    assert task.status == "todo" and task.priority == "P2"


def test_link_unique_per_task_kind_ref(db):
    owner = make_user(db, "tc_link")
    task = TaskItem(owner_id=owner.id, title="挂文档")
    db.add(task)
    db.flush()
    db.add(TaskLink(task_id=task.id, kind="doc", ref="docs/a.md", title="a"))
    db.flush()
    db.add(TaskLink(task_id=task.id, kind="doc", ref="docs/a.md", title="a"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_brief_unique_per_owner_and_date(db):
    from datetime import date
    owner = make_user(db, "tc_brief")
    db.add(TaskBrief(owner_id=owner.id, brief_date=date(2026, 9, 30), content_json={}, source="template"))
    db.flush()
    db.add(TaskBrief(owner_id=owner.id, brief_date=date(2026, 9, 30), content_json={}, source="template"))
    with pytest.raises(IntegrityError):
        db.flush()
