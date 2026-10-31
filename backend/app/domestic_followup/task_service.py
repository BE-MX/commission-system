"""跟进任务：source_key 幂等创建、关闭、顺延、转交、条目处理、待办查询（规格 3.5 / 4.5）。"""
import logging
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup import visibility
from app.domestic_followup.constants import (
    CLOSE_ITEM_RESOLVED, CLOSE_NEW_FOLLOWUP, CLOSE_RECEIPT_DONE, OPEN_ITEM_STATES, TRACKED_KINDS, URGENT,
)
from app.domestic_followup.models import DomesticFollowupItem, DomesticFollowupTask

logger = logging.getLogger("commission")

Task = DomesticFollowupTask
CLOSABLE_BY_FOLLOWUP = ("plan", "receipt")


def upsert_task(db: Session, *, source_key: str, task_type: str, customer_id: int, assignee_user_id: int,
                title: str, due_date: date, payload: dict | None = None,
                source_followup_id: int | None = None, source_item_id: int | None = None) -> tuple[Task, bool]:
    existing = db.query(Task).filter(Task.source_key == source_key).first()
    if existing:
        return existing, False
    task = Task(task_type=task_type, customer_id=customer_id, assignee_user_id=assignee_user_id,
                source_key=source_key, title=title[:200], due_date=due_date, payload=payload,
                source_followup_id=source_followup_id, source_item_id=source_item_id)
    savepoint = db.begin_nested()
    try:
        db.add(task)
        db.flush()
        savepoint.commit()
    except IntegrityError as exc:
        savepoint.rollback()  # 并发下另一事务先建了同一来源的任务，取它即可
        logger.warning("followup task insert conflict source_key=%s: %s", source_key, type(exc.orig).__name__)
        print(f"[domestic_followup] task insert conflict source_key={source_key}", flush=True)
        try:
            # InnoDB 默认 REPEATABLE READ：普通 SELECT 读旧快照看不到对方刚提交的行，加锁读才读最新版本
            return (db.query(Task).filter(Task.source_key == source_key)
                    .populate_existing().with_for_update().one()), False
        except NoResultFound:
            raise exc from None  # 不是同一来源撞键（如 NOT NULL / FK），把原始错误抛出去，不要掩盖
    return task, True


def close_task(task: Task, status: str, reason: str, *, followup_id: int | None = None,
               user_id: int | None = None) -> bool:
    if task.status != "todo":
        return False
    task.status = status
    task.closed_reason = reason
    task.closed_by_followup_id = followup_id
    task.closed_by_user_id = user_id
    task.closed_at = beijing_now()
    return True


def create_plan_task(db: Session, followup, shop_name: str) -> Task | None:
    if not followup.next_date or followup.customer_id is None:
        return None
    task, _ = upsert_task(
        db, source_key=f"plan:{followup.id}", task_type="plan", customer_id=followup.customer_id,
        assignee_user_id=followup.author_user_id, title=f"{shop_name}：{followup.next_plan or '约定跟进'}",
        due_date=followup.next_date, payload={"plan": followup.next_plan, "method": followup.next_method},
        source_followup_id=followup.id,
    )
    return task


def create_item_task(db: Session, item: DomesticFollowupItem, followup, shop_name: str) -> Task:
    label = "异常" if item.kind == "issue" else "意见"
    task, _ = upsert_task(
        db, source_key=f"item:{item.id}", task_type=item.kind, customer_id=item.customer_id,
        assignee_user_id=item.handler_user_id or followup.author_user_id,
        title=f"{shop_name}：{label}·{item.text}", due_date=followup.followup_date,
        payload={"category": item.category, "severity": item.severity},
        source_followup_id=followup.id, source_item_id=item.id,
    )
    return task


def close_tasks_for_followup(db: Session, current_user: dict, customer_id: int, task_ids, followup_id: int) -> list[int]:
    """确认跟进时关闭勾选的旧待办：只关本客户、未完成的约定跟进与收货回访。

    每张都按 is_task_actor 口径过一遍：只因被转交了一张异常待办而能写客户的人，
    不能顺手关掉归属人的回访。不满足的静默跳过（不是错误，只是不归他关）。
    """
    ids = sorted({int(i) for i in (task_ids or []) if i})
    if not ids:
        return []
    rows = (
        db.query(Task)
        .filter(Task.id.in_(ids), Task.customer_id == customer_id, Task.status == "todo",
                Task.task_type.in_(CLOSABLE_BY_FOLLOWUP))
        .with_for_update()
        .all()
    )
    closed = []
    for task in rows:
        if not is_task_actor(db, current_user, task):
            continue
        reason = CLOSE_RECEIPT_DONE if task.task_type == "receipt" else CLOSE_NEW_FOLLOWUP
        if close_task(task, "done", reason, followup_id=followup_id, user_id=visibility.uid(current_user)):
            closed.append(task.id)
    db.flush()
    return closed


def is_task_actor(db: Session, current_user: dict, task: Task) -> bool:
    """负责人本人，或在客户范围内（含 read_all）。"""
    if task.assignee_user_id == visibility.uid(current_user):
        return True
    return visibility.in_customer_scope(db, current_user, task.customer_id)


def ensure_task_actor(db: Session, current_user: dict, task: Task) -> None:
    if not is_task_actor(db, current_user, task):
        raise PermissionError("这不是你的待办")


def snooze(db: Session, current_user: dict, task_id: int, *, days: int = 1, today: date | None = None) -> Task:
    if not 1 <= days <= 7:
        raise ValueError("顺延天数需在 1~7 天")
    task = db.query(Task).filter(Task.id == task_id).with_for_update().first()
    if task is None:
        raise LookupError("待办不存在")
    ensure_task_actor(db, current_user, task)
    if task.status != "todo":
        raise ValueError("该待办已结束")
    task.due_date = max(task.due_date, today or beijing_today()) + timedelta(days=days)
    task.snooze_count += 1
    db.flush()
    return task


def _locked_item(db: Session, item_id: int) -> DomesticFollowupItem:
    item = db.query(DomesticFollowupItem).filter(DomesticFollowupItem.id == item_id).with_for_update().first()
    if item is None or item.kind not in TRACKED_KINDS:
        raise LookupError("条目不存在")
    return item


def _ensure_item_actor(db: Session, current_user: dict, item: DomesticFollowupItem) -> None:
    if item.handler_user_id == visibility.uid(current_user):
        return
    if visibility.in_customer_scope(db, current_user, item.customer_id):
        return
    raise PermissionError("无权处理该条目")


def transfer_item(db: Session, current_user: dict, item_id: int, to_user_id: int, *, note: str | None = None):
    item = _locked_item(db, item_id)
    _ensure_item_actor(db, current_user, item)
    if item.status not in OPEN_ITEM_STATES:
        raise ValueError("该条目已处理，不能转交")
    target = db.query(ArkUser).filter(ArkUser.id == to_user_id, ArkUser.is_active.is_(True),
                                      ArkUser.deleted_at.is_(None)).first()
    if target is None:
        raise ValueError("接收人不存在或已停用")
    previous = item.handler_user_id
    item.handler_user_id = target.id
    item.status = "handling"
    for task in db.query(Task).filter(Task.source_item_id == item.id, Task.status == "todo").all():
        task.assignee_user_id = target.id
        task.payload = {**(task.payload or {}), "transferred_from": previous, "transfer_note": (note or "")[:200]}
    db.flush()
    return item


def resolve_item(db: Session, current_user: dict, item_id: int, *, status: str, resolution: str | None,
                 followup_id: int | None = None):
    if status not in ("resolved", "closed_no_action"):
        raise ValueError("处理状态不合法")
    item = _locked_item(db, item_id)
    _ensure_item_actor(db, current_user, item)
    if item.status not in OPEN_ITEM_STATES:
        raise ValueError("该条目已处理")
    item.status = status
    item.resolution = (resolution or "").strip()[:500] or None
    item.resolved_at = beijing_now()
    item.resolved_by_followup_id = followup_id
    for task in db.query(Task).filter(Task.source_item_id == item.id, Task.status == "todo").all():
        close_task(task, "done", CLOSE_ITEM_RESOLVED, followup_id=followup_id, user_id=visibility.uid(current_user))
    db.flush()
    return item


def _name_map(db: Session, column_id, column_name, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.query(column_id, column_name).filter(column_id.in_(ids)).all())


def serialize_tasks(db: Session, rows: list[Task], today: date) -> list[dict]:
    shops = _name_map(db, DomesticCustomer.id, DomesticCustomer.shop_name, [r.customer_id for r in rows])
    users = _name_map(db, ArkUser.id, ArkUser.real_name, [r.assignee_user_id for r in rows])
    return [{
        "id": r.id, "task_type": r.task_type, "customer_id": r.customer_id,
        "shop_name": shops.get(r.customer_id), "assignee_user_id": r.assignee_user_id,
        "assignee_name": users.get(r.assignee_user_id), "title": r.title,
        "due_date": r.due_date.isoformat(), "status": r.status, "snooze_count": r.snooze_count,
        "overdue_days": max((today - r.due_date).days, 0) if r.status == "todo" else 0,
        "payload": r.payload or {}, "source_followup_id": r.source_followup_id,
        "source_item_id": r.source_item_id, "closed_reason": r.closed_reason,
    } for r in rows]


def list_tasks(db: Session, current_user: dict, *, scope: str = "mine", status: str = "todo",
               task_type: str | None = None, customer_id: int | None = None, due: str = "all",
               page: int = 1, page_size: int = 50, today: date | None = None) -> dict:
    today = today or beijing_today()
    query = db.query(Task)
    if scope == "mine":
        query = query.filter(Task.assignee_user_id == visibility.uid(current_user))
    else:
        condition = visibility.task_filter(current_user)
        if condition is not None:
            query = query.filter(condition)
    if status:
        query = query.filter(Task.status == status)
    if task_type == "issue":  # 前端「异常意见」tab 同时看 issue 与 suggestion
        query = query.filter(Task.task_type.in_(TRACKED_KINDS))
    elif task_type:
        query = query.filter(Task.task_type == task_type)
    if customer_id:
        query = query.filter(Task.customer_id == customer_id)
    if due == "today":
        query = query.filter(Task.due_date <= today)
    elif due == "upcoming":
        query = query.filter(Task.due_date > today)
    total = query.count()
    rows = query.order_by(Task.due_date, Task.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": serialize_tasks(db, rows, today), "total": total, "page": page, "page_size": page_size}


def summary(db: Session, current_user: dict, *, today: date | None = None) -> dict:
    """「我的」未完成待办计数：今天及以前到期的按类型计，未来到期的计入 upcoming。"""
    today = today or beijing_today()
    rows = db.query(Task.task_type, Task.due_date, Task.payload).filter(
        Task.assignee_user_id == visibility.uid(current_user), Task.status == "todo"
    ).all()
    result = {"receipt": 0, "plan": 0, "issue": 0, "urgent": 0, "upcoming": 0}
    for task_type, due_date, payload in rows:
        if due_date > today:
            result["upcoming"] += 1
            continue
        result["issue" if task_type in TRACKED_KINDS else task_type] += 1
        if task_type in TRACKED_KINDS and (payload or {}).get("severity") == URGENT:
            result["urgent"] += 1
    return result


def list_items(db: Session, current_user: dict, *, status: str = "open", kind: str | None = None,
               category: str | None = None, customer_id: int | None = None, mine: bool = False,
               page: int = 1, page_size: int = 50) -> dict:
    """异常意见看板：open 含 handling；按创建时间倒序。"""
    from app.domestic_followup.followup_service import serialize_item  # 序列化口径与时间线一致

    query = db.query(DomesticFollowupItem).filter(DomesticFollowupItem.kind.in_(TRACKED_KINDS))
    if status == "open":
        query = query.filter(DomesticFollowupItem.status.in_(OPEN_ITEM_STATES))
    elif status:
        query = query.filter(DomesticFollowupItem.status == status)
    if kind in TRACKED_KINDS:
        query = query.filter(DomesticFollowupItem.kind == kind)
    if category:
        query = query.filter(DomesticFollowupItem.category == category)
    if customer_id:
        query = query.filter(DomesticFollowupItem.customer_id == customer_id)
    user_id = visibility.uid(current_user)
    if mine:
        query = query.filter(DomesticFollowupItem.handler_user_id == user_id)
    elif not visibility.can_read_all(current_user):
        query = query.filter((DomesticFollowupItem.handler_user_id == user_id)
                             | DomesticFollowupItem.customer_id.in_(visibility.scoped_customer_ids(user_id)))
    total = query.count()
    rows = (query.order_by(DomesticFollowupItem.created_at.desc(), DomesticFollowupItem.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    shops = _name_map(db, DomesticCustomer.id, DomesticCustomer.shop_name, [r.customer_id for r in rows])
    handlers = _name_map(db, ArkUser.id, ArkUser.real_name, [r.handler_user_id for r in rows])
    items = [{**serialize_item(r), "shop_name": shops.get(r.customer_id),
              "handler_name": handlers.get(r.handler_user_id)} for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def search_users(db: Session, q: str, limit: int = 20) -> list[dict]:
    """转交选人：在职用户按姓名/用户名模糊搜，只返回 id 与姓名。"""
    query = db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
    keyword = (q or "").strip()
    if keyword:
        query = query.filter((ArkUser.real_name.contains(keyword)) | (ArkUser.username.contains(keyword)))
    return [{"id": uid, "real_name": name} for uid, name in query.order_by(ArkUser.real_name).limit(limit).all()]
