"""PM Hub 任务看板：轻量四状态流转，受阻必填原因，关联资料。"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.pm.material_service import get_material
from app.pm.models import PmTask, PmTaskMaterial, bj_now
from app.pm.service import audit

logger = logging.getLogger("commission")

VALID_TASK_STATUSES = ("todo", "in_progress", "done", "blocked")


def get_task(db: Session, task_id: int, include_deleted: bool = False) -> Optional[PmTask]:
    q = db.query(PmTask).filter(PmTask.id == task_id)
    if not include_deleted:
        q = q.filter(PmTask.deleted_at.is_(None))
    return q.first()


def _linked_materials(db: Session, task_ids: list[int]) -> dict[int, list[dict]]:
    """任务卡上直接显示关联资料的当前状态徽标。"""
    if not task_ids:
        return {}
    from app.pm.models import PmMaterial
    rows = (
        db.query(PmTaskMaterial.task_id, PmMaterial)
        .join(PmMaterial, PmMaterial.id == PmTaskMaterial.material_id)
        .filter(PmTaskMaterial.task_id.in_(task_ids), PmMaterial.deleted_at.is_(None))
        .all()
    )
    result: dict[int, list[dict]] = {}
    for task_id, m in rows:
        result.setdefault(task_id, []).append(
            {"id": m.id, "name": m.name, "status": m.status, "importance": m.importance}
        )
    return result


def task_to_dict(t: PmTask, materials: Optional[list[dict]] = None) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "blocked_reason": t.blocked_reason,
        "assignee": t.assignee,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "phase": t.phase,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat(sep=" ") if t.created_at else None,
        "updated_at": t.updated_at.isoformat(sep=" ") if t.updated_at else None,
        "materials": materials or [],
    }


def list_tasks(db: Session, project_id: int, assignee: Optional[str] = None,
               phase: Optional[int] = None) -> list[dict]:
    q = db.query(PmTask).filter(PmTask.project_id == project_id, PmTask.deleted_at.is_(None))
    if assignee:
        q = q.filter(PmTask.assignee == assignee)
    if phase:
        q = q.filter(PmTask.phase == phase)
    tasks = q.order_by(PmTask.sort_order, PmTask.id).all()
    links = _linked_materials(db, [t.id for t in tasks])
    return [task_to_dict(t, links.get(t.id, [])) for t in tasks]


def _set_material_links(db: Session, task: PmTask, material_ids: list[int]) -> None:
    db.query(PmTaskMaterial).filter(PmTaskMaterial.task_id == task.id).delete()
    for mid in dict.fromkeys(material_ids or []):
        if get_material(db, mid):
            db.add(PmTaskMaterial(task_id=task.id, material_id=mid))
    db.flush()


def create_task(db: Session, project_id: int, username: str, data: dict) -> PmTask:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("标题必填")
    status = data.get("status") or "todo"
    if status not in VALID_TASK_STATUSES:
        raise ValueError("状态不合法")
    blocked_reason = (data.get("blocked_reason") or "").strip() or None
    if status == "blocked" and not blocked_reason:
        raise ValueError("受阻状态必须填写受阻原因")
    task = PmTask(
        project_id=project_id,
        title=title,
        description=(data.get("description") or "").strip() or None,
        status=status,
        blocked_reason=blocked_reason,
        assignee=data.get("assignee") or None,
        due_date=data.get("due_date") or None,
        phase=data.get("phase"),
        created_by=username,
    )
    db.add(task)
    db.flush()
    _set_material_links(db, task, data.get("material_ids") or [])
    audit(db, project_id, username, "create_task", "task", task.id, task.title)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task: PmTask, username: str, data: dict) -> PmTask:
    changes: dict = {}
    if "title" in data and data["title"] and data["title"].strip() != task.title:
        changes["title"] = {"from": task.title, "to": data["title"].strip()}
        task.title = data["title"].strip()
    if "status" in data and data["status"] and data["status"] != task.status:
        if data["status"] not in VALID_TASK_STATUSES:
            raise ValueError("状态不合法")
        changes["status"] = {"from": task.status, "to": data["status"]}
        task.status = data["status"]
        if task.status != "blocked":
            task.blocked_reason = None
    if "blocked_reason" in data or task.status == "blocked":
        new_reason = (data.get("blocked_reason") or "").strip() or None
        if task.status == "blocked" and not new_reason:
            raise ValueError("受阻状态必须填写受阻原因")
        if new_reason != task.blocked_reason:
            changes["blocked_reason"] = {"from": task.blocked_reason, "to": new_reason}
            task.blocked_reason = new_reason
    for field in ("description", "assignee"):
        if field in data:
            new_val = (data[field] or "").strip() or None
            if new_val != getattr(task, field):
                changes[field] = {"from": getattr(task, field), "to": new_val}
                setattr(task, field, new_val)
    if "due_date" in data:
        new_due = data["due_date"] or None
        if new_due != task.due_date:
            changes["due_date"] = {"from": task.due_date.isoformat() if task.due_date else None,
                                   "to": new_due.isoformat() if hasattr(new_due, "isoformat") else new_due}
            task.due_date = new_due
    if "phase" in data and data["phase"] != task.phase:
        changes["phase"] = {"from": task.phase, "to": data["phase"]}
        task.phase = data["phase"]
    if "material_ids" in data:
        _set_material_links(db, task, data.get("material_ids") or [])
        changes["materials"] = {"to": data.get("material_ids") or []}
    if not changes:
        return task
    task.updated_at = bj_now()
    audit(db, task.project_id, username, "update_task", "task", task.id, task.title, changes)
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: PmTask, username: str) -> None:
    task.deleted_at = bj_now()
    audit(db, task.project_id, username, "delete_task", "task", task.id, task.title)
    db.commit()
