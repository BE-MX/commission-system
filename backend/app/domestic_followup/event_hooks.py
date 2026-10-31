"""客户归属变化 → 迁移或取消跟进待办（规格 4.5 客户转移）。

挂在 Session before_flush 上，覆盖内贸主模块所有改 owner_user_id 的路径，
不改 app/domestic/*。改动直接写 ORM 对象，并入同一次 flush 与同一事务。
"""
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.domestic.models import DomesticCustomer
from app.domestic_followup.constants import CLOSE_RELEASED
from app.domestic_followup.models import DomesticFollowupTask

OWNER_BOUND_TYPES = ("plan", "receipt")


def _old_owner(session: Session, customer: DomesticCustomer):
    history = inspect(customer).attrs.owner_user_id.history
    if history.deleted:
        return history.deleted[0]
    if not history.added:
        return customer.owner_user_id  # 未改动
    table = DomesticCustomer.__table__
    return session.connection().execute(
        select(table.c.owner_user_id).where(table.c.id == customer.id)).scalar()


@event.listens_for(Session, "before_flush")
def move_followup_tasks(session, _context, _instances):
    changes = []
    for row in session.dirty:
        if not isinstance(row, DomesticCustomer) or not inspect(row).attrs.owner_user_id.history.has_changes():
            continue
        old, new = _old_owner(session, row), row.owner_user_id
        if old is not None and old != new:
            changes.append((row.id, old, new))
    if not changes:
        return
    with session.no_autoflush:
        for customer_id, old, new in changes:
            tasks = session.query(DomesticFollowupTask).filter(
                DomesticFollowupTask.customer_id == customer_id, DomesticFollowupTask.status == "todo",
                DomesticFollowupTask.task_type.in_(OWNER_BOUND_TYPES),
                DomesticFollowupTask.assignee_user_id == old,
            ).all()
            for task in tasks:
                if new is None:
                    task.status = "cancelled"
                    task.closed_reason = CLOSE_RELEASED
                    task.closed_at = beijing_now()
                else:
                    task.assignee_user_id = new
