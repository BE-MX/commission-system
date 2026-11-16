from sqlalchemy import select

from app.domestic.models import DomesticCustomer
from app.domestic_followup import task_service, visibility
from app.domestic_followup.collaboration_models import FollowupResponsibility
from app.domestic_followup.models import DomesticFollowupTask


def current_owner(db, customer: DomesticCustomer) -> int | None:
    responsibility = db.scalar(select(FollowupResponsibility).where(
        FollowupResponsibility.customer_id == customer.id,
    ))
    return responsibility.owner_user_id if responsibility is not None else customer.owner_user_id


def can_read(db, user, prep, customer: DomesticCustomer | None = None) -> bool:
    customer = customer or db.get(DomesticCustomer, prep.customer_id)
    if customer is None:
        return False
    user_id = visibility.uid(user)
    if current_owner(db, customer) == user_id:
        return True
    return prep.author_user_id == user_id and visibility.in_customer_scope(db, user, customer.id)


def ensure_read(db, user, prep, customer: DomesticCustomer | None = None) -> None:
    if not can_read(db, user, prep, customer):
        raise PermissionError("无权查看该准备卡")


def ensure_author(db, user, prep) -> DomesticCustomer:
    customer = db.get(DomesticCustomer, prep.customer_id)
    ensure_read(db, user, prep, customer)
    if prep.author_user_id != visibility.uid(user):
        raise PermissionError("当前负责人只能只读查看，只有作者可以修改")
    return customer


def ensure_context_write(db, user, customer_id: int, source_task_id: int | None = None) -> DomesticCustomer:
    customer = db.get(DomesticCustomer, customer_id)
    if customer is None:
        raise LookupError("客户不存在")
    if source_task_id is not None:
        task = db.get(DomesticFollowupTask, source_task_id)
        if task is None or task.customer_id != customer_id or task.status != "todo":
            raise ValueError("来源待办已结束或不属于该客户")
        task_service.ensure_task_actor(db, user, task)
        return customer
    return visibility.ensure_customer_writable(db, user, customer_id)
