"""发送任务队列的查询与人工撤销（P1 不含认领/租约，属 worker 阶段）。"""

from sqlalchemy.orm import Session

from app.customer.models import CustomerAccount
from app.mail_outreach.errors import conflict, not_found
from app.mail_outreach.generation_service import _iso_bj, _iso_utc
from app.mail_outreach.models import MailOutreachMessage, MailOutreachSendJob

# 可人工撤销的前置状态；sending 之后一律冲突，终态幂等返回
_CANCELLABLE_STATUSES = ("scheduled", "claimed", "blocked", "needs_review")
_TERMINAL_STATUSES = ("cancelled", "provider_accepted", "failed_safe", "ambiguous")


def serialize_job(job: MailOutreachSendJob, *, customer_name: str | None = None) -> dict:
    return {
        "id": job.id,
        "idempotency_key": job.idempotency_key,
        "approval_id": job.approval_id,
        "message_id": job.message_id,
        "revision_id": job.revision_id,
        "mailbox_binding_id": job.mailbox_binding_id,
        "to_contact_point_id": job.to_contact_point_id,
        "to_email_snapshot": job.to_email_snapshot,
        "status": job.status,
        "due_at": _iso_bj(job.due_at),
        "due_at_utc": _iso_utc(job.due_at_utc),
        "lease_owner": job.lease_owner,
        "lease_until_utc": _iso_utc(job.lease_until_utc),
        "fencing_token": job.fencing_token,
        "send_started_at_utc": _iso_utc(job.send_started_at_utc),
        "reschedule_count": job.reschedule_count,
        "blocked_reason": job.blocked_reason,
        "cancel_note": job.cancel_note,
        "customer_name": customer_name,
        "created_at": _iso_bj(job.created_at),
        "updated_at": _iso_bj(job.updated_at),
    }


def list_jobs(
    db: Session,
    *,
    status: str | None = None,
    mailbox_binding_id: int | None = None,
    customer_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """队列看板：状态/邮箱/客户筛选 + 分页，关联 message 取客户展示字段。"""
    query = db.query(MailOutreachSendJob)
    if status:
        query = query.filter(MailOutreachSendJob.status == status)
    if mailbox_binding_id is not None:
        query = query.filter(MailOutreachSendJob.mailbox_binding_id == mailbox_binding_id)
    if customer_id is not None:
        query = query.filter(
            MailOutreachSendJob.message_id.in_(
                db.query(MailOutreachMessage.id).filter(
                    MailOutreachMessage.customer_id == customer_id,
                )
            )
        )
    total = query.count()
    jobs = query.order_by(MailOutreachSendJob.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()

    message_ids = {job.message_id for job in jobs}
    messages = {
        row.id: row for row in db.query(MailOutreachMessage).filter(
            MailOutreachMessage.id.in_(message_ids),
        ).all()
    } if message_ids else {}
    customer_ids = {message.customer_id for message in messages.values()}
    customers = {
        row.id: row.display_name for row in db.query(CustomerAccount).filter(
            CustomerAccount.id.in_(customer_ids),
        ).all()
    } if customer_ids else {}

    items = []
    for job in jobs:
        message = messages.get(job.message_id)
        item = serialize_job(
            job,
            customer_name=customers.get(message.customer_id) if message else None,
        )
        if message is not None:
            item["customer_id"] = message.customer_id
            item["contact_id"] = message.contact_id
            item["relationship_goal"] = message.relationship_goal
        items.append(item)
    return items, total


def cancel_job(db: Session, job_id: int, note: str = "") -> dict:
    """人工撤销：前置状态转 cancelled；已进通道调用报冲突；终态幂等返回。"""
    job = db.query(MailOutreachSendJob).filter(
        MailOutreachSendJob.id == job_id,
    ).with_for_update().one_or_none()
    if job is None:
        raise not_found("任务不存在")
    if job.status == "sending" or job.send_started_at_utc is not None:
        raise conflict("任务已进通道调用，无法撤销", error_code="cancel_too_late")
    if job.status in _TERMINAL_STATUSES:
        return serialize_job(job)
    if job.status not in _CANCELLABLE_STATUSES:
        raise conflict(f"任务当前状态为 {job.status}，不可撤销", error_code="invalid_status")
    job.status = "cancelled"
    job.cancel_note = note or "manual_cancel"
    db.commit()
    return serialize_job(job)


__all__ = ["cancel_job", "list_jobs", "serialize_job"]
