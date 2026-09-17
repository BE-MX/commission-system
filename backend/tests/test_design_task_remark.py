"""Task remarks use isolated SQLite fixtures."""
from datetime import date
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.design.models import DesignScheduleRequest, DesignScheduleTask
from app.design.request_service import update_task_remark
from app.design.schemas import TaskRemarkUpdate

def test_task_remark_is_independent_and_can_be_cleared(db):
    req = DesignScheduleRequest(request_no="remark-request", customer_name="Test", salesperson_id=1, salesperson_name="Tester",
        shoot_type="photo", expect_start_date=date(2026,9,17), expect_end_date=date(2026,9,17),
        remark="request note", status="scheduled")
    db.add(req)
    db.flush()
    task = DesignScheduleTask(request_id=req.id, task_no="remark-task", designer_id=1,
        remark="old note", status="scheduled")
    db.add(task)
    db.commit()
    for value in ["new note\nsecond line", ""]:
        update_task_remark(db, task.id, value)
        db.refresh(task)
        db.refresh(req)
        assert task.remark == value
        assert req.remark == "request note"
        assert task.status == req.status == "scheduled"
    req.deleted_at = req.created_at
    db.commit()
    with pytest.raises(HTTPException) as exc:
        update_task_remark(db, task.id, "must not save")
    assert exc.value.status_code == 404

def test_missing_task(db):
    with pytest.raises(HTTPException) as exc:
        update_task_remark(db, 999999, "note")
    assert exc.value.status_code == 404

def test_failed_commit_rolls_back():
    db = Mock()
    db.commit.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        update_task_remark(db, 1, "note")
    db.rollback.assert_called_once()

@pytest.mark.parametrize("payload", [{}, {"remark": None}, {"remark": {"text": "note"}}])
def test_remark_requires_explicit_text(payload):
    with pytest.raises(ValidationError):
        TaskRemarkUpdate.model_validate(payload)
