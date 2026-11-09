"""Apply current follow-up responsibility when saving records or handling an assigned task."""
from datetime import datetime, time

from sqlalchemy import select

from app.core.time import beijing_today
from app.domestic.models import DomesticCustomer
from app.domestic_followup import collaboration_access, task_service, visibility
from app.domestic_followup.collaboration_models import FollowupCollaborator, FollowupResponsibility
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupTask


def _assigned_task(db, user, customer_id, task_id, *, lock=False):
    if task_id is None:
        return None
    query = select(DomesticFollowupTask).where(
        DomesticFollowupTask.id == task_id, DomesticFollowupTask.customer_id == customer_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = db.scalar(query)
    if task is None or task.status != "todo":
        raise ValueError("关联待办已结束或不属于该客户，请刷新")
    task_service.ensure_task_actor(db, user, task, lock=lock)
    return task


def draft_access(db, user, customer_id, task_id):
    customer = db.get(DomesticCustomer, customer_id)
    if task_id is not None and customer is not None and customer.status == 1:
        _assigned_task(db, user, customer_id, task_id)
        return
    visibility.ensure_customer_writable(db, user, customer_id)


def can_record_history(db, user, customer, *, lock=False):
    if customer.status != 1 or not collaboration_access.claims_allow(user, collaboration_access.WRITE):
        return False
    if collaboration_access.customer_is_managed(db, customer, lock=lock) and not collaboration_access.has_live_write(
            db, user, lock=lock):
        return False
    previously_authored = db.scalar(select(DomesticFollowup.id).where(
        DomesticFollowup.customer_id == customer.id, DomesticFollowup.author_user_id == visibility.uid(user),
        DomesticFollowup.status == "confirmed",
    ).limit(1))
    return bool(previously_authored or visibility.in_legacy_customer_scope(db, user, customer.id)
                or visibility.is_super_admin(user) or collaboration_access.has_history_access(db, user, customer))


def _historical_allowed(db, user, customer, followup, fields):
    if followup.followup_date >= beijing_today():
        raise ValueError("历史补录请选择今天以前的实际沟通日期")
    if (fields.next_date or fields.next_plan or fields.next_method or fields.development_stage
            or fields.plan_assignee_user_id
            or fields.close_task_ids or fields.resolved_items or followup.source_task_id
            or fields.shared_summary or fields.effective_progress or any(item.kind != "content" for item in fields.items)):
        raise ValueError("历史补录只保存沟通事实，请移除待办、共享摘要或当前进度变更")
    if not can_record_history(db, user, customer, lock=True):
        raise PermissionError("你没有该客户的历史补录权限")


def confirm_access(db, user, followup, fields):
    from app.domestic_followup.followup_service import ConflictError

    customer = collaboration_access.lock_customer(db, fields.customer_id)
    if customer is None:
        raise LookupError("客户不存在")
    if fields.historical_only:
        _historical_allowed(db, user, customer, followup, fields)
        return customer, None, False
    if customer.status != 1:
        raise PermissionError("该客户已停用，不能记录跟进")
    responsibility = db.scalar(select(FollowupResponsibility).where(
        FollowupResponsibility.customer_id == customer.id,
    ).with_for_update().execution_options(populate_existing=True))
    task = _assigned_task(db, user, customer.id, followup.source_task_id, lock=True)
    may_develop = visibility.can_write_customer(db, user, customer, lock=True)
    if not may_develop:
        service_task = task and (task.task_type in ("receipt", "issue", "suggestion") or (
            task.task_type == "plan" and task.purpose in ("maintenance", "other")
        ))
        if not service_task:
            visibility.ensure_customer_writable(db, user, customer.id, lock=True)
        if (fields.next_date or fields.next_plan or fields.next_method or fields.development_stage
                or fields.plan_assignee_user_id
                or fields.effective_progress or fields.shared_summary
                or set(fields.close_task_ids) - {task.id}
                or any(resolved.item_id != task.source_item_id for resolved in fields.resolved_items)):
            raise PermissionError("此权限仅用于处理已分配的待办")
        return customer, responsibility, True
    if responsibility and (fields.next_date or fields.development_stage):
        if fields.responsibility_version != responsibility.version:
            raise ConflictError("跟进责任或下一步安排已变更，请刷新后重试")
        if followup.followup_date != beijing_today():
            raise ValueError("历史沟通可单独补录，当前进度和计划请用今天的记录更新")
        if fields.next_date and not fields.plan_purpose:
            raise ValueError("请选择计划用途")
        if fields.development_stage == "paused":
            promised = fields.next_date if fields.plan_purpose == "development" else responsibility.next_plan_date
            if not promised or promised <= beijing_today():
                raise ValueError("暂缓开发请保留一个未来的联系约定")
    return customer, responsibility, False


def plan_assignee(db, responsibility, fields):
    selected = fields.plan_assignee_user_id
    if selected is None:
        return responsibility.owner_user_id if responsibility and fields.plan_purpose == "development" else None
    if responsibility is None or not fields.next_date or not fields.plan_purpose:
        raise ValueError("指定计划承办人前，请填写当前协作客户的计划日期及用途")
    if selected != responsibility.owner_user_id and db.get(
            FollowupCollaborator, (responsibility.customer_id, selected), with_for_update={"read": True},
            populate_existing=True) is None:
        raise ValueError("计划承办人须为当前跟进负责人或正式协作人")
    if not collaboration_access.qualified(db, selected, responsibility.customer_id, lock=True):
        raise PermissionError("所选承办人已失去本客户跟进资格，请刷新")
    return selected


def sync_development_date(db, responsibility):
    if responsibility is None or responsibility.owner_user_id is None:
        return False
    next_date = db.scalar(select(DomesticFollowupTask.due_date).where(
        DomesticFollowupTask.customer_id == responsibility.customer_id,
        DomesticFollowupTask.task_type == "plan", DomesticFollowupTask.purpose == "development",
        DomesticFollowupTask.status == "todo",
    ).order_by(DomesticFollowupTask.due_date, DomesticFollowupTask.id).limit(1).with_for_update())
    if next_date == responsibility.next_plan_date:
        return False
    responsibility.next_plan_date = next_date
    return True


def update_responsibility(db, responsibility, followup, fields):
    if not responsibility:
        return
    changed = sync_development_date(db, responsibility)
    if fields.development_stage and fields.development_stage != responsibility.stage:
        responsibility.stage = fields.development_stage
        changed = True
    if fields.effective_progress:
        occurred = datetime.combine(followup.followup_date, time.min)
        if responsibility.last_progress_at is None or occurred > responsibility.last_progress_at:
            responsibility.last_progress_at = occurred
    if changed:
        responsibility.version += 1
