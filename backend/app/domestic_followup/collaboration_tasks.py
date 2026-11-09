"""Handoff task selection and concurrency-safe execution."""
from sqlalchemy import select

from app.core.time import beijing_now
from app.domestic_followup.models import DomesticFollowupTask


class ConflictError(Exception):
    """A client must reload current responsibility, handoff or task state."""


def active_tasks(db, customer_id, *, lock=False):
    stmt = select(DomesticFollowupTask).where(
        DomesticFollowupTask.customer_id == customer_id, DomesticFollowupTask.status == "todo",
    ).order_by(DomesticFollowupTask.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalars(stmt).all()


def task_decision(task, owner_id, coordinator=False, *, closing=False):
    belongs_to_owner = task.assignee_user_id == owner_id
    needs_coordinator_assignment = coordinator and (closing or owner_id is None)
    if task.task_type == "plan":
        if task.purpose == "development":
            if belongs_to_owner or needs_coordinator_assignment:
                return "transfer"
            if coordinator:
                return "optional"
        if task.purpose is None:
            if belongs_to_owner or needs_coordinator_assignment:
                return "choose"
            if coordinator:
                return "optional"
    if task.task_type == "receipt" and (belongs_to_owner or coordinator) and not closing:
        return "optional"
    return "retain"


def task_rows(tasks, owner_id, coordinator=False, *, closing=False):
    return [
        {
            "id": task.id,
            "task_type": task.task_type,
            "purpose": task.purpose,
            "assignee_user_id": task.assignee_user_id,
            "due_date": task.due_date.isoformat(),
            "title": task.title,
            "decision": task_decision(task, owner_id, coordinator, closing=closing),
            "revision": task.updated_at.isoformat(),
        }
        for task in tasks
    ]


def plan_tasks(rows, payload, *, releasing=False):
    transfer = set(payload.transfer_task_ids)
    keep = set(payload.keep_task_ids)
    cancel = set(payload.cancel_task_ids)
    if transfer & keep or transfer & cancel or keep & cancel:
        raise ValueError("每条待办只能选择一种处理方式")
    if cancel and not releasing:
        raise ValueError("只能在释放或停止开发时结束开发待办")
    if releasing and transfer:
        raise ValueError("继续进行的开发待办请先通过交接或重派交由新负责人")
    decisions = {row["id"]: row["decision"] for row in rows}
    if (transfer | keep | cancel) - decisions.keys():
        raise ConflictError("待办已变化，请刷新后重新核对")
    required = {task_id for task_id, decision in decisions.items() if decision == "transfer"}
    undecided = {task_id for task_id, decision in decisions.items() if decision == "choose"}
    optional = {task_id for task_id, decision in decisions.items() if decision == "optional"}
    if undecided - (transfer | keep | cancel):
        raise ValueError("请逐条选择如何处理未分类计划")
    if releasing and required - (transfer | cancel):
        raise ValueError("请逐条确认结束开发待办；如需继续进行，请发起交接")
    if (transfer - (required | undecided | optional) or cancel - (required | undecided)
            or keep - undecided):
        raise ValueError("所选待办不能用该方式处理")
    if not releasing:
        transfer |= required
    return {"transfer": sorted(transfer), "keep": sorted(keep), "cancel": sorted(cancel)}


def package_tasks(rows, plan):
    """Package only selected task details. Keep the rest as drift-only metadata."""
    selected = set(plan["transfer"]) | set(plan["cancel"])
    fingerprint = [
        [row["id"], row["decision"], row["revision"], row["assignee_user_id"], row["due_date"], row["title"],
         row["purpose"]]
        for row in rows if row["decision"] in ("transfer", "choose") or row["id"] in selected
    ]
    return {
        "plan": plan,
        "fingerprint": fingerprint,
        "preview": [{key: value for key, value in row.items() if key != "revision"}
                    for row in rows if row["id"] in selected],
    }


def execute_plan(tasks, plan, recipient_id, actor):
    if plan["transfer"] and recipient_id is None:
        raise ValueError("请选择承接待办的合格人员")
    task_map = {task.id: task for task in tasks}
    for task_id in plan["transfer"]:
        task = task_map[task_id]
        task.assignee_user_id = recipient_id
        if task.task_type == "plan" and task.purpose is None:
            task.purpose = "development"
    for task_id in plan["cancel"]:
        task = task_map[task_id]
        task.status = "cancelled"
        task.closed_at = beijing_now()
        task.closed_by_user_id = actor
        task.closed_reason = "协作开发终止"
    for task_id in plan["keep"]:
        task_map[task_id].purpose = "other"
