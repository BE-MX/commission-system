"""任务中心核心服务：CRUD、树规则、状态机、回收站、统计。

个人任务规模有限（千级），树操作一次载入 owner 全部未删除任务在内存计算，
比递归 SQL 简单可靠；所有查询都带 owner_id，跨 owner 一律视为不存在（404）。
"""
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today
from app.task import module_service
from app.task.errors import TaskConflict, TaskInvalid, TaskNotFound
from app.task.models import (
    CLOSED_STATUSES, MAX_DEPTH, OPEN_STATUSES, PRIORITIES, SOURCES, STATUS_LABELS, STATUSES,
    TaskEvent, TaskItem, TaskLink, LINK_KINDS,
)

EDITABLE_FIELDS = ("title", "description", "acceptance", "priority", "module_key", "due_date")
MAX_ACCEPTANCE = 8


# ── 基础 ────────────────────────────────────────────────────────────────

def _event(db: Session, task_id: int, type_: str, payload: dict | None = None, actor: str = "user") -> None:
    db.add(TaskEvent(task_id=task_id, actor=actor, type=type_, payload_json=payload or {}))


def get_task(db: Session, owner_id: int, task_id: int, include_deleted: bool = False) -> TaskItem:
    q = db.query(TaskItem).filter(TaskItem.id == task_id, TaskItem.owner_id == owner_id)
    if not include_deleted:
        q = q.filter(TaskItem.deleted_at.is_(None))
    task = q.first()
    if task is None:
        raise TaskNotFound("任务不存在")
    return task


def _owner_tasks(db: Session, owner_id: int) -> dict[int, TaskItem]:
    rows = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.is_(None)).all()
    return {t.id: t for t in rows}


def _children_map(tasks: dict[int, TaskItem]) -> dict[int | None, list[TaskItem]]:
    result: dict[int | None, list[TaskItem]] = {}
    for t in tasks.values():
        result.setdefault(t.parent_id, []).append(t)
    for siblings in result.values():
        siblings.sort(key=lambda x: (x.sort_order, x.id))
    return result


def _depth(tasks: dict[int, TaskItem], task_id: int | None) -> int:
    """task_id 所在层级（顶层=1）；None 表示根之上，返回 0。"""
    depth, current = 0, task_id
    while current is not None:
        depth += 1
        current = tasks[current].parent_id if current in tasks else None
    return depth


def _descendant_ids(children: dict, task_id: int) -> list[int]:
    out, stack = [], [task_id]
    while stack:
        for child in children.get(stack.pop(), []):
            out.append(child.id)
            stack.append(child.id)
    return out


def _subtree_height(children: dict, task_id: int) -> int:
    kids = children.get(task_id, [])
    return 1 + max((_subtree_height(children, k.id) for k in kids), default=0)


def _clean_title(title) -> str:
    title = (title or "").strip()
    if not title or len(title) > 200:
        raise TaskInvalid("标题需为 1~200 个字")
    return title


def _clean_acceptance(items) -> list[str] | None:
    if items is None:
        return None
    if not isinstance(items, list):
        raise TaskInvalid("验收标准需为列表")
    cleaned = [str(x).strip()[:200] for x in items if str(x).strip()]
    return cleaned[:MAX_ACCEPTANCE]


def _clean_priority(priority) -> str:
    if priority not in PRIORITIES:
        raise TaskInvalid("重要性只能是 P0~P3")
    return priority


def _clean_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise TaskInvalid("日期格式应为 YYYY-MM-DD") from exc


# ── 创建 / 更新 / 移动 ─────────────────────────────────────────────────

def create_task(db: Session, owner_id: int, *, title, description=None, acceptance=None, priority="P2",
                module_key=None, parent_id=None, due_date=None, source="manual") -> TaskItem:
    if source not in SOURCES:
        raise TaskInvalid("未知的创建来源")
    title = _clean_title(title)
    priority = _clean_priority(priority)
    module_key = module_service.ensure_usable(db, owner_id, module_key)
    tasks = _owner_tasks(db, owner_id)
    if parent_id is not None:
        get_task(db, owner_id, parent_id)
        if _depth(tasks, parent_id) + 1 > MAX_DEPTH:
            raise TaskInvalid(f"任务最多 {MAX_DEPTH} 层，不能再往下加子任务")
    siblings = [t for t in tasks.values() if t.parent_id == parent_id]
    task = TaskItem(
        owner_id=owner_id, parent_id=parent_id, title=title, description=description,
        acceptance=_clean_acceptance(acceptance), priority=priority, module_key=module_key,
        due_date=_clean_date(due_date), source=source,
        sort_order=max((t.sort_order for t in siblings), default=0) + 1,
    )
    db.add(task)
    db.flush()
    _event(db, task.id, "created", {"source": source})
    db.flush()
    return task


def update_task(db: Session, owner_id: int, task_id: int, changes: dict) -> TaskItem:
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise TaskInvalid(f"不能直接修改字段：{', '.join(sorted(unknown))}")
    task = get_task(db, owner_id, task_id)
    for field, value in changes.items():
        if field == "title":
            value = _clean_title(value)
        elif field == "acceptance":
            value = _clean_acceptance(value)
        elif field == "priority":
            value = _clean_priority(value)
        elif field == "module_key":
            value = module_service.ensure_usable(db, owner_id, value)
        elif field == "due_date":
            value = _clean_date(value)
        setattr(task, field, value)
    if changes:
        _event(db, task.id, "updated", {"fields": sorted(changes)})
    db.flush()
    return task


def move_task(db: Session, owner_id: int, task_id: int, new_parent_id: int | None) -> TaskItem:
    task = get_task(db, owner_id, task_id)
    tasks = _owner_tasks(db, owner_id)
    children = _children_map(tasks)
    if new_parent_id is not None:
        get_task(db, owner_id, new_parent_id)
        if new_parent_id == task_id or new_parent_id in _descendant_ids(children, task_id):
            raise TaskInvalid("不能把任务移动到它自己或它的子任务下面")
        if _depth(tasks, new_parent_id) + _subtree_height(children, task_id) > MAX_DEPTH:
            raise TaskInvalid(f"移动后会超过 {MAX_DEPTH} 层")
    old_parent = task.parent_id
    task.parent_id = new_parent_id
    siblings = children.get(new_parent_id, [])
    task.sort_order = max((t.sort_order for t in siblings), default=0) + 1
    _event(db, task.id, "moved", {"from": old_parent, "to": new_parent_id})
    db.flush()
    return task


# ── 序列化 / 树 ────────────────────────────────────────────────────────

def serialize_task(task: TaskItem) -> dict:
    return {
        "id": task.id, "code": task.code, "parent_id": task.parent_id, "title": task.title,
        "description": task.description, "acceptance": task.acceptance or [],
        "priority": task.priority, "status": task.status, "blocked_reason": task.blocked_reason,
        "module_key": task.module_key, "due_date": task.due_date.isoformat() if task.due_date else None,
        "source": task.source, "sort_order": task.sort_order,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _leaf_progress(children: dict, task: TaskItem) -> tuple[int, int]:
    kids = children.get(task.id, [])
    if not kids:
        return (1 if task.status in CLOSED_STATUSES else 0, 1)
    done = total = 0
    for k in kids:
        d, t = _leaf_progress(children, k)
        done, total = done + d, total + t
    return done, total


def list_tree(db: Session, owner_id: int) -> list[dict]:
    tasks = _owner_tasks(db, owner_id)
    children = _children_map(tasks)

    def build(task: TaskItem) -> dict:
        node = serialize_task(task)
        kids = children.get(task.id, [])
        node["children"] = [build(k) for k in kids]
        if kids:
            done, total = _leaf_progress(children, task)
            node["progress"] = {"done": done, "total": total}
        return node

    return [build(t) for t in children.get(None, [])]

# ── 状态机 ─────────────────────────────────────────────────────────────
# 迁移矩阵见设计文档第 3 节。done 只有 user 可写；ai/mcp 只能提议 pending_confirm（二期起用）。

_OPEN = set(OPEN_STATUSES)


def can_transition(actor: str, frm: str, to: str) -> bool:
    if frm == to:
        return False
    if actor == "user":
        if frm in _OPEN:
            return to in _OPEN | {"done", "shelved"}
        if frm == "pending_confirm":
            return to in {"in_progress", "done"}
        if frm in CLOSED_STATUSES:
            return to == "todo"
        return False
    if actor in ("ai", "mcp"):
        return frm in _OPEN and to == "pending_confirm"
    return False


def change_status(db: Session, owner_id: int, task_id: int, to: str, *, actor: str = "user",
                  reason: str | None = None, confirm_open_children: bool = False) -> TaskItem:
    if to not in STATUSES:
        raise TaskInvalid("未知状态")
    task = get_task(db, owner_id, task_id)
    frm = task.status
    if not can_transition(actor, frm, to):
        raise TaskConflict(f"不能从「{STATUS_LABELS[frm]}」改为「{STATUS_LABELS[to]}」", code="transition")
    reason = (reason or "").strip() or None
    if to == "blocked" and not reason:
        raise TaskInvalid("标记受阻需要填写原因")
    if frm == "pending_confirm" and to == "in_progress" and not reason:
        raise TaskInvalid("驳回完成提议需要填写原因")
    if to == "done" and not confirm_open_children:
        tasks = _owner_tasks(db, owner_id)
        open_count = sum(1 for i in _descendant_ids(_children_map(tasks), task.id)
                         if tasks[i].status not in CLOSED_STATUSES)
        if open_count:
            raise TaskConflict(f"还有 {open_count} 个子任务没结束", code="open_children",
                               extra={"open_children": open_count})
    task.status = to
    task.blocked_reason = reason if to == "blocked" else None
    task.completed_at = beijing_now() if to == "done" else None
    _event(db, task.id, "status_changed", {"from": frm, "to": to, "reason": reason}, actor=actor)
    db.flush()
    return task


# ── 回收站 ─────────────────────────────────────────────────────────────

def delete_task(db: Session, owner_id: int, task_id: int) -> None:
    task = get_task(db, owner_id, task_id)
    children = _children_map(_owner_tasks(db, owner_id))
    stamp, batch = beijing_now(), uuid.uuid4().hex
    ids = [task.id, *_descendant_ids(children, task.id)]
    db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.id.in_(ids)).update(
        {TaskItem.deleted_at: stamp, TaskItem.delete_batch: batch}, synchronize_session="fetch")
    _event(db, task.id, "deleted", {"count": len(ids)})
    db.flush()


def list_trash(db: Session, owner_id: int) -> list[dict]:
    rows = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.isnot(None)).all()
    by_id = {t.id: t for t in rows}
    roots = [t for t in rows if t.parent_id not in by_id or by_id[t.parent_id].delete_batch != t.delete_batch]
    roots.sort(key=lambda t: (t.deleted_at, t.id), reverse=True)
    return [serialize_task(t) | {"deleted_at": t.deleted_at.isoformat()} for t in roots]


def restore_task(db: Session, owner_id: int, task_id: int) -> TaskItem:
    task = get_task(db, owner_id, task_id, include_deleted=True)
    if task.deleted_at is None:
        raise TaskConflict("任务没有被删除")
    batch = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.delete_batch == task.delete_batch).all()
    children: dict = {}
    for t in batch:
        children.setdefault(t.parent_id, []).append(t)
    ids = {task.id, *_descendant_ids(children, task.id)}
    if task.parent_id is not None:
        parent = db.query(TaskItem).filter(TaskItem.id == task.parent_id, TaskItem.owner_id == owner_id).first()
        if parent is None or parent.deleted_at is not None:
            task.parent_id = None
    for t in batch:
        if t.id in ids:
            t.deleted_at = None
            t.delete_batch = None
    _event(db, task.id, "restored", {"count": len(ids)})
    db.flush()
    return task


# ── 关联 ───────────────────────────────────────────────────────────────

def _clean_ref(kind: str, ref: str) -> str:
    ref = (ref or "").strip().replace("\\", "/")
    if not ref or len(ref) > 500:
        raise TaskInvalid("关联地址需为 1~500 个字符")
    if kind == "url":
        if not ref.startswith(("https://", "http://")):
            raise TaskInvalid("链接需以 http:// 或 https:// 开头")
    elif ".." in ref.split("/") or ref.startswith("/"):
        raise TaskInvalid("仓库路径需为 docs/ 等相对路径，不能包含 ..")
    return ref


def add_link(db: Session, owner_id: int, task_id: int, *, kind: str, ref: str, title: str = "") -> TaskLink:
    if kind not in LINK_KINDS:
        raise TaskInvalid("一期只支持挂文档、原型或链接")
    task = get_task(db, owner_id, task_id)
    ref = _clean_ref(kind, ref)
    exists = db.query(TaskLink).filter_by(task_id=task.id, kind=kind, ref=ref).first()
    if exists:
        raise TaskConflict("这条关联已经存在")
    link = TaskLink(task_id=task.id, kind=kind, ref=ref, title=(title or "").strip()[:200] or ref.rsplit("/", 1)[-1])
    db.add(link)
    db.flush()
    _event(db, task.id, "linked", {"kind": kind, "ref": ref})
    db.flush()
    return link


def remove_link(db: Session, owner_id: int, link_id: int) -> None:
    link = db.query(TaskLink).filter(TaskLink.id == link_id).first()
    if link is None:
        raise TaskNotFound("关联不存在")
    get_task(db, owner_id, link.task_id)
    _event(db, link.task_id, "unlinked", {"kind": link.kind, "ref": link.ref})
    db.delete(link)
    db.flush()


def serialize_link(link: TaskLink) -> dict:
    return {"id": link.id, "kind": link.kind, "ref": link.ref, "title": link.title,
            "match": link.match, "status": link.status}


def task_detail(db: Session, owner_id: int, task_id: int) -> dict:
    task = get_task(db, owner_id, task_id)
    tasks = _owner_tasks(db, owner_id)
    children = _children_map(tasks)
    path, cur = [], task.parent_id
    while cur is not None and cur in tasks:
        path.insert(0, {"id": cur, "code": tasks[cur].code, "title": tasks[cur].title})
        cur = tasks[cur].parent_id
    links = db.query(TaskLink).filter(TaskLink.task_id == task.id).order_by(TaskLink.id).all()
    events = (db.query(TaskEvent).filter(TaskEvent.task_id == task.id)
              .order_by(TaskEvent.id.desc()).limit(50).all())
    detail = serialize_task(task)
    detail.update({
        "path": path,
        "children": [serialize_task(c) for c in children.get(task.id, [])],
        "links": [serialize_link(l) for l in links],
        "events": [{"id": e.id, "actor": e.actor, "type": e.type, "payload": e.payload_json or {},
                    "created_at": e.created_at.isoformat()} for e in events],
    })
    if children.get(task.id):
        done, total = _leaf_progress(children, task)
        detail["progress"] = {"done": done, "total": total}
    return detail


# ── 统计 ───────────────────────────────────────────────────────────────

def stats(db: Session, owner_id: int, today: date | None = None) -> dict:
    today = today or beijing_today()
    tasks = [t for t in _owner_tasks(db, owner_id).values() if t.status not in CLOSED_STATUSES]
    return {
        "in_progress": sum(1 for t in tasks if t.status == "in_progress"),
        "pending_confirm": sum(1 for t in tasks if t.status == "pending_confirm"),
        "p0_open": sum(1 for t in tasks if t.priority == "P0"),
        "overdue": sum(1 for t in tasks if t.due_date and t.due_date < today),
    }
