"""Reconcile edited plans without reopening completed business facts."""
from app.auth.models import ArkUser
from app.domestic_followup import task_service
from app.domestic_followup.models import DomesticFollowupTask as Task

EDIT_CANCEL_REASON = "跟进修改取消"


def assignee(db, candidates):
    for user_id in dict.fromkeys(candidates):
        if user_id and db.query(ArkUser.id).filter(ArkUser.id == user_id, ArkUser.is_active.is_(True),
                                                  ArkUser.deleted_at.is_(None)).first():
            return user_id
    raise ValueError("关联待办没有有效负责人，请先分配客户归属或启用负责人")


def cancel(task, actor_id, followup_id):
    task_service.close_task(task, "cancelled", EDIT_CANCEL_REASON,
                            user_id=actor_id, followup_id=followup_id)


def sync_plan(db, followup, customer, previous, tasks, actor_id):
    plans = [t for t in tasks if t.source_followup_id == followup.id and t.task_type == "plan"]
    active = [t for t in plans if t.status == "todo"]
    if len(active) > 1:
        raise ValueError("存在多张未完成约定跟进，请先核查关联待办")
    changed_date = previous["next_date"] != (followup.next_date.isoformat() if followup.next_date else None)
    if not followup.next_date:
        for task in active:
            cancel(task, actor_id, followup.id)
        return
    if active:
        task = active[0]
        if changed_date:
            task.due_date = followup.next_date
        task.title = f"{customer.shop_name}：{followup.next_plan or '约定跟进'}"[:200]
        task.payload = {**(task.payload or {}), "plan": followup.next_plan, "method": followup.next_method}
        return
    # A text-only correction must never recreate a completed/cancelled plan.
    if not changed_date:
        return
    last = max(plans, key=lambda t: t.id) if plans else None
    target = assignee(db, [last.assignee_user_id if last else None, customer.owner_user_id, followup.author_user_id])
    task_service.upsert_task(
        db, source_key=f"plan:{followup.id}:edit:{followup.version + 1}", task_type="plan",
        customer_id=customer.id, assignee_user_id=target, source_followup_id=followup.id,
        title=f"{customer.shop_name}：{followup.next_plan or '约定跟进'}", due_date=followup.next_date,
        payload={"plan": followup.next_plan, "method": followup.next_method},
        purpose=last.purpose if last else None)


def sync_item(db, item, followup, customer, tasks, actor_id, *, old_date, allow_create=False):
    active = [t for t in tasks if t.source_item_id == item.id and t.status == "todo"]
    if item.status not in ("open", "handling"):
        for task in active:
            cancel(task, actor_id, followup.id)
        return
    for task in active:
        label = "异常" if item.kind == "issue" else "意见"
        task.title = f"{customer.shop_name}：{label}·{item.text}"[:200]
        task.payload = {**(task.payload or {}), "category": item.category, "severity": item.severity}
        # Keep manual snoozes and transferred assignees.
        if old_date != followup.followup_date and not task.snooze_count:
            task.due_date = followup.followup_date
    if not active and allow_create:
        label = "异常" if item.kind == "issue" else "意见"
        target = assignee(db, [item.handler_user_id, customer.owner_user_id, followup.author_user_id])
        item.handler_user_id = target
        task_service.upsert_task(
            db, source_key=f"item:{item.id}:edit:{followup.version + 1}", task_type=item.kind,
            customer_id=customer.id, assignee_user_id=target, source_followup_id=followup.id,
            source_item_id=item.id, title=f"{customer.shop_name}：{label}·{item.text}",
            due_date=followup.followup_date, payload={"category": item.category, "severity": item.severity})
