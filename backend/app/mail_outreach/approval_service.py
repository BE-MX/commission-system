"""逐封审批：哈希锁定 + 资格复查 + 同事务建 job + 失效/撤销。

approve 单事务口径（设计文档 §五/§六）：
锁 message 行 → 校验版本归属与 expected_content_sha256 → 资格复查 →
复核发件邮箱绑定 → 计算 approval_sha256 → 插 approval → 同事务建 send job。
并发重复批准由 message 行锁 + approval_id/idempotency_key 唯一约束兜底，
重复点击幂等返回既有结果。
"""

from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now, to_beijing_naive
from app.customer.access_service import CustomerAccess
from app.customer.models import CustomerContactPoint
from app.mail_outreach import policies
from app.mail_outreach.eligibility_service import evaluate_email_eligibility
from app.mail_outreach.errors import bad_request, conflict, forbidden, not_found
from app.mail_outreach.generation_service import BLOCKING_RISK_CODES, _iso_bj, _iso_utc
from app.mail_outreach.job_service import serialize_job
from app.mail_outreach.models import (
    MailMailboxBinding,
    MailOutreachApproval,
    MailOutreachMessage,
    MailOutreachRevision,
    MailOutreachSendJob,
)


def _require_human(db: Session, user: dict) -> int:
    """审批人必须是活跃的方舟真人账号（对齐 governance _require_human 口径）。"""
    try:
        user_id = int(user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise forbidden("审批人必须为活跃方舟用户", error_code="approver_invalid") from exc
    row = db.query(ArkUser.id).filter(
        ArkUser.id == user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).one_or_none()
    if row is None:
        raise forbidden("审批人必须为活跃方舟用户", error_code="approver_invalid")
    return user_id


def serialize_approval(approval: MailOutreachApproval) -> dict:
    return {
        "id": approval.id,
        "message_id": approval.message_id,
        "revision_id": approval.revision_id,
        "approver_user_id": approval.approver_user_id,
        "decision": approval.decision,
        "reason": approval.reason,
        "mailbox_binding_id": approval.mailbox_binding_id,
        "to_contact_point_id": approval.to_contact_point_id,
        "to_email_snapshot": approval.to_email_snapshot,
        "approval_sha256": approval.approval_sha256,
        "scheduled_at_utc": _iso_utc(approval.scheduled_at_utc),
        "scheduled_at_local": approval.scheduled_at_local,
        "scheduled_at_beijing": _iso_bj(approval.scheduled_at_beijing),
        "reschedule_policy": approval.reschedule_policy_json,
        "expires_at": _iso_bj(approval.expires_at),
        "decided_at": _iso_bj(approval.decided_at),
        "revoked_at": _iso_bj(approval.revoked_at),
        "revoke_reason": approval.revoke_reason,
    }


def _lock_message(db: Session, message_id: int) -> MailOutreachMessage:
    message = db.query(MailOutreachMessage).filter(
        MailOutreachMessage.id == message_id,
    ).with_for_update().one_or_none()
    if message is None:
        raise not_found("草稿不存在")
    return message


def _active_approval(db: Session, message_id: int) -> MailOutreachApproval | None:
    return db.query(MailOutreachApproval).filter(
        MailOutreachApproval.message_id == message_id,
        MailOutreachApproval.decision == "approved",
        MailOutreachApproval.revoked_at.is_(None),
    ).one_or_none()


def _result(message: MailOutreachMessage, approval: MailOutreachApproval, job, *, replay: bool) -> dict:
    return {
        "message_status": message.status,
        "approval": serialize_approval(approval),
        "job": serialize_job(job) if job is not None else None,
        "idempotent_replay": replay,
    }


def _normalize_scheduled_utc(value) -> tuple:
    """协议入参统一为 UTC：naive 按 UTC 解释（对齐 to_beijing_naive 的协议约定）。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value, value.astimezone(timezone.utc).replace(tzinfo=None)


def approve(db: Session, access: CustomerAccess, user: dict, message_id: int, payload) -> dict:
    approver_id = _require_human(db, user)
    message = _lock_message(db, message_id)

    # 幂等：同事务内已有生效批准则直接返回既有结果（并发双击只产生一个 job）
    existing = _active_approval(db, message.id)
    if existing is not None:
        job = db.query(MailOutreachSendJob).filter(
            MailOutreachSendJob.approval_id == existing.id,
        ).one_or_none()
        return _result(message, existing, job, replay=True)

    if message.status != "draft":
        raise conflict(f"草稿当前状态为 {message.status}，不可批准", error_code="message_not_draft")
    revision = db.query(MailOutreachRevision).filter(
        MailOutreachRevision.id == payload.revision_id,
    ).one_or_none()
    if (
        revision is None
        or revision.message_id != message.id
        or message.current_revision_id != revision.id
    ):
        raise conflict("批准版本不是该草稿的当前版本", error_code="revision_mismatch")

    recomputed = policies.compute_content_sha256(
        subject=revision.subject,
        body_text=revision.body_text,
        language_tag=revision.language_tag,
        claims=revision.claims_json,
    )
    if recomputed != revision.content_sha256 or recomputed != payload.expected_content_sha256:
        raise conflict("内容已变化，批准哈希不一致，请刷新后重试", error_code="content_hash_mismatch")

    blocking = [
        flag for flag in (revision.risk_flags_json or [])
        if isinstance(flag, dict) and flag.get("code") in BLOCKING_RISK_CODES
    ]
    if blocking:
        detail = "；".join(str(flag.get("detail") or flag["code"]) for flag in blocking[:3])
        raise conflict(f"存在阻断性风险标记，不可批准：{detail}", error_code="risk_blocked")

    # 审批时点资格复查（临发复查属 worker 阶段，P1 不做）
    eligibility = evaluate_email_eligibility(
        db, access, message.customer_id, message.contact_id, message.contact_point_id,
    )
    if not eligibility["eligible"]:
        raise conflict(
            "触达资格复查未通过：" + "；".join(eligibility["reasons"]),
            error_code="eligibility_failed",
        )

    mailbox = db.query(MailMailboxBinding).filter(
        MailMailboxBinding.id == payload.mailbox_binding_id,
    ).one_or_none()
    if mailbox is None or mailbox.status != "active" or mailbox.pause_reason:
        raise bad_request("发件邮箱绑定不存在、已停用或已暂停", error_code="mailbox_unavailable")
    point = db.query(CustomerContactPoint).filter(
        CustomerContactPoint.id == message.contact_point_id,
    ).one_or_none()
    if point is None:
        raise conflict("收件邮箱点已不存在", error_code="contact_point_missing")

    scheduled_aware, scheduled_utc_naive = _normalize_scheduled_utc(payload.scheduled_at_utc)
    scheduled_local = None
    if revision.recipient_timezone:
        try:
            scheduled_local = scheduled_aware.astimezone(
                ZoneInfo(revision.recipient_timezone),
            ).isoformat()
        except (ValueError, KeyError):
            scheduled_local = None

    approval_sha256 = policies.compute_approval_sha256(
        content_sha256=revision.content_sha256,
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=point.id,
        to_email_snapshot=point.normalized_value,
        language_tag=revision.language_tag,
        schedule_policy=dict(payload.schedule_policy or {}),
        scheduled_at_utc=scheduled_aware.isoformat(),
    )
    approval = MailOutreachApproval(
        message_id=message.id,
        revision_id=revision.id,
        approver_user_id=approver_id,
        decision="approved",
        reason=payload.reason or "",
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=point.id,
        to_email_snapshot=point.normalized_value,
        approval_sha256=approval_sha256,
        scheduled_at_utc=scheduled_utc_naive,
        scheduled_at_local=scheduled_local,
        scheduled_at_beijing=to_beijing_naive(scheduled_aware, naive_is_beijing=False),
        reschedule_policy_json=dict(payload.schedule_policy or {}),
        decided_at=beijing_now(),
    )
    db.add(approval)
    db.flush()  # 先拿到 approval.id 再建 job（approval_id 唯一约束兜底并发）
    job = MailOutreachSendJob(
        idempotency_key=policies.job_idempotency_key(message.id, revision.id),
        approval_id=approval.id,
        message_id=message.id,
        revision_id=revision.id,
        mailbox_binding_id=mailbox.id,
        to_contact_point_id=point.id,
        to_email_snapshot=point.normalized_value,
        status="scheduled",
        due_at=to_beijing_naive(scheduled_aware, naive_is_beijing=False),
        due_at_utc=scheduled_utc_naive,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        # 唯一约束兜底：并发另一事务已先行批准，回滚后按幂等返回既有结果
        db.rollback()
        existing = _active_approval(db, message_id)
        if existing is not None:
            existing_job = db.query(MailOutreachSendJob).filter(
                MailOutreachSendJob.approval_id == existing.id,
            ).one_or_none()
            existing_message = db.query(MailOutreachMessage).filter(
                MailOutreachMessage.id == message_id,
            ).one_or_none()
            return _result(existing_message, existing, existing_job, replay=True)
        raise conflict("并发批准冲突，请刷新后重试", error_code="approval_conflict")

    message.status = "approved"
    db.commit()
    return _result(message, approval, job, replay=False)


def reject(db: Session, access: CustomerAccess, user: dict, message_id: int, reason: str) -> dict:
    approver_id = _require_human(db, user)
    message = _lock_message(db, message_id)
    if message.status != "draft":
        raise conflict(f"草稿当前状态为 {message.status}，不可拒绝", error_code="message_not_draft")
    approval = MailOutreachApproval(
        message_id=message.id,
        revision_id=message.current_revision_id,
        approver_user_id=approver_id,
        decision="rejected",
        reason=reason,
        to_contact_point_id=message.contact_point_id,
        decided_at=beijing_now(),
    )
    db.add(approval)
    message.status = "rejected"
    db.commit()
    return {"message_status": message.status, "approval": serialize_approval(approval)}


def revoke(db: Session, access: CustomerAccess, user: dict, message_id: int, reason: str) -> dict:
    _require_human(db, user)
    message = _lock_message(db, message_id)
    approval = _active_approval(db, message.id)
    if approval is None:
        raise conflict("不存在生效中的批准，无法撤销", error_code="approval_missing")
    job = db.query(MailOutreachSendJob).filter(
        MailOutreachSendJob.approval_id == approval.id,
    ).one_or_none()
    if job is not None and job.send_started_at_utc is not None:
        raise conflict("任务已进通道调用，无法撤回", error_code="revoke_too_late")
    approval.revoked_at = beijing_now()
    approval.revoke_reason = reason
    if job is not None and job.status in ("scheduled", "claimed", "blocked", "needs_review"):
        job.status = "cancelled"
        job.cancel_note = f"approval_revoked: {reason}"
    message.status = "cancelled"
    db.commit()
    return _result(message, approval, job, replay=False)


__all__ = ["approve", "reject", "revoke", "serialize_approval"]
