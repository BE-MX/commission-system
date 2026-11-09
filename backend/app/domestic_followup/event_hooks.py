"""客户归属变化 → 迁移或取消跟进待办（规格 4.5 客户转移、第六节客户释放）。

挂在 Session before_flush 上，覆盖内贸主模块所有改 owner_user_id 的路径，
不改 app/domestic/*。改动直接写 ORM 对象，并入同一次 flush 与同一事务。

原归属联动仅用于尚无独立跟进责任的客户。只动约定跟进 / 收货回访：
- 公海 → 新归属人：公海期间是临时承接，该客户所有未完成的约定跟进 / 回访转给新归属人；
- 旧 → 新：只转旧归属人名下的，不抢提成人等其他人自己承诺的约定跟进；
- 旧 → 公海：该客户所有未完成的约定跟进 / 回访以「客户释放」取消。
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
        if old != new:
            changes.append((row.id, old, new))
    if not changes:
        return
    with session.no_autoflush:
        from app.domestic_followup.collaboration_models import FollowupResponsibility
        independent = set(session.scalars(
            select(FollowupResponsibility.customer_id).where(
                FollowupResponsibility.customer_id.in_([customer_id for customer_id, _, _ in changes])
            )
        ))
        for customer_id, old, new in changes:
            if customer_id in independent:
                continue
            query = session.query(DomesticFollowupTask).filter(
                DomesticFollowupTask.customer_id == customer_id, DomesticFollowupTask.status == "todo",
                DomesticFollowupTask.task_type.in_(OWNER_BOUND_TYPES),
            )
            if old is not None and new is not None:
                query = query.filter(DomesticFollowupTask.assignee_user_id == old)
            for task in query.all():
                if new is None:
                    task.status = "cancelled"
                    task.closed_reason = CLOSE_RELEASED
                    task.closed_at = beijing_now()
                else:
                    task.assignee_user_id = new
