"""公海释放 / 认领对跟进责任的联动（2026-11-13 Q5、Q6）。由 app.domestic.customer_service 在同一事务内调用。

- 因「1 个月未跟进」释放：责任回到待分配、清协作人、作废待处理交接、取消约定跟进与收货回访。
  系统任务没有操作人，协作事件表要求操作人非空，所以这一步不写协作事件；归属变化由分析事件表记录。
- 认领：责任没人在跟（无负责人，或状态不是跟进中 / 交接中，如已停止开发）时交给认领人并补客户级协作范围，
  否则认领人记不了跟进、一个月后又会被释放。仍有人在跟（11-09 D07「公海 · 某某跟进中」）时不动，由协作流程交接。
"""
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.domestic_followup.collaboration_models import (
    FollowupCollaborationEvent, FollowupCollaborator, FollowupHandoff, FollowupResponsibility, FollowupScope,
)
from app.domestic_followup.constants import CLOSE_RELEASED
from app.domestic_followup.event_hooks import OWNER_BOUND_TYPES
from app.domestic_followup.models import DomesticFollowupTask

FOLLOW_RELEASE_REASON = "1 个月未跟进，自动释放入公海"


def end_for_follow_release(db: Session, customer_ids: list[int]) -> None:
    if not customer_ids:
        return
    now = beijing_now()
    with db.no_autoflush:
        for responsibility in db.scalars(select(FollowupResponsibility).where(
                FollowupResponsibility.customer_id.in_(customer_ids)).with_for_update()):
            responsibility.owner_user_id = None
            responsibility.status = "unassigned"
            responsibility.next_plan_date = None
            responsibility.version += 1
        for member in db.scalars(select(FollowupCollaborator).where(FollowupCollaborator.customer_id.in_(customer_ids))):
            db.delete(member)
        for handoff in db.scalars(select(FollowupHandoff).where(
                FollowupHandoff.customer_id.in_(customer_ids), FollowupHandoff.status == "pending").with_for_update()):
            handoff.status = "invalidated"
            handoff.pending_marker = None
            handoff.version += 1
            handoff.handled_at = now
            handoff.handling_reason = FOLLOW_RELEASE_REASON
        for task in db.scalars(select(DomesticFollowupTask).where(
                DomesticFollowupTask.customer_id.in_(customer_ids), DomesticFollowupTask.status == "todo",
                DomesticFollowupTask.task_type.in_(OWNER_BOUND_TYPES)).with_for_update()):
            task.status = "cancelled"
            task.closed_reason = CLOSE_RELEASED
            task.closed_at = now


def adopt_on_claim(db: Session, customer_id: int, user_id: int) -> None:
    responsibility = db.scalar(select(FollowupResponsibility).where(
        FollowupResponsibility.customer_id == customer_id).with_for_update())
    if responsibility is None:
        return
    if responsibility.owner_user_id is not None and responsibility.status in ("following", "handoff"):
        return  # 仍有人在跟（11-09 D07），由协作流程交接
    previous = responsibility.owner_user_id
    responsibility.owner_user_id = user_id
    responsibility.status = "following"
    responsibility.stage = responsibility.stage if responsibility.stage not in (None, "paused") else "new"
    responsibility.next_plan_date = None
    responsibility.allow_future_contact = None
    responsibility.version += 1
    scope_key = f"c:{customer_id}"
    if db.scalar(select(FollowupScope.id).where(FollowupScope.user_id == user_id,
                                                 FollowupScope.scope_key == scope_key)) is None:
        db.add(FollowupScope(user_id=user_id, customer_id=customer_id, scope_key=scope_key, added_by_user_id=user_id))
    db.add(FollowupCollaborationEvent(
        customer_id=customer_id, actor_user_id=user_id, action="claim", from_user_id=previous, to_user_id=user_id,
        reason="从公海认领客户", responsibility_version=responsibility.version,
        idempotency_key=f"public-sea-claim:{uuid4().hex}",
    ))
