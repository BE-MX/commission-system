"""Mailbox-bound leases and single-use send authorization.

Lock order for content transitions: customer, mailbox, message, job. A send
authorization is consumed before touching the provider; uncertainty never retries.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_

from app.auth.service import get_live_user_authorization
from app.core.config import get_settings
from app.core.time import beijing_now, utc_now_naive
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.models import CustomerAccount, CustomerContactPoint
from app.mail_outreach import policies
from app.mail_outreach.context_service import build_outreach_snapshot
from app.mail_outreach.eligibility_service import evaluate_email_eligibility
from app.mail_outreach.errors import conflict, not_found
from app.mail_outreach.generation_service import BLOCKING_RISK_CODES
from app.mail_outreach.job_service import serialize_job
from app.mail_outreach.models import (
    MailEventCheckpoint, MailMailboxBinding, MailOutreachApproval,
    MailOutreachMessage, MailOutreachRevision, MailOutreachSendAttempt, MailOutreachSendJob,
)


def utc_now():
    return utc_now_naive()


def allowed_recipients():
    return {x.strip().lower() for x in get_settings().MAIL_OUTREACH_ALLOWED_RECIPIENTS.split(",") if x.strip()}


def binding(db, identity, mailbox_id, *, lock=False):
    query = db.query(MailMailboxBinding).filter_by(id=mailbox_id, worker_identity=identity)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise not_found("邮箱绑定不存在")
    return row


def mailbox_ready(db, mailbox):
    checkpoint = db.get(MailEventCheckpoint, mailbox.id)
    return bool(mailbox.status == "active" and mailbox.auth_status == "active"
                and not mailbox.pause_reason and checkpoint
                and checkpoint.last_polled_at_utc
                and checkpoint.last_polled_at_utc >= utc_now() - timedelta(minutes=3))


def heartbeat(db, identity, mailbox_id, payload):
    mailbox = binding(db, identity, mailbox_id, lock=True)
    if payload.sender_email.lower() != mailbox.sender_email.lower():
        mailbox.auth_status = "unknown"
        db.commit()
        raise conflict("CLI 发件地址与绑定不一致", error_code="sender_mismatch")
    mailbox.auth_status = payload.auth_status
    checkpoint = db.get(MailEventCheckpoint, mailbox.id)
    if checkpoint is None:
        checkpoint = MailEventCheckpoint(mailbox_binding_id=mailbox.id)
        db.add(checkpoint)
    checkpoint.last_polled_at_utc = utc_now()
    checkpoint.watch_health = "ok" if payload.auth_status == "active" else "down"
    db.commit()
    return {"ready": mailbox_ready(db, mailbox)}


def claim(db, identity, mailbox_id):
    mailbox = binding(db, identity, mailbox_id, lock=True)
    now = utc_now()
    # A worker disappearing after authorization can never cause a second send.
    db.query(MailOutreachSendJob).filter(
        MailOutreachSendJob.mailbox_binding_id == mailbox_id,
        MailOutreachSendJob.status == "sending",
        MailOutreachSendJob.lease_until_utc < now,
    ).update({"status": "ambiguous", "blocked_reason": "worker_result_missing"}, synchronize_session=False)
    if not get_settings().MAIL_OUTREACH_SEND_ENABLED or not mailbox_ready(db, mailbox):
        db.commit()
        return None
    job = db.query(MailOutreachSendJob).filter(
        MailOutreachSendJob.mailbox_binding_id == mailbox_id,
        MailOutreachSendJob.send_started_at_utc.is_(None),
        MailOutreachSendJob.due_at_utc <= now,
        or_(MailOutreachSendJob.status == "scheduled",
            (MailOutreachSendJob.status == "claimed") & (MailOutreachSendJob.lease_until_utc < now)),
    ).order_by(MailOutreachSendJob.due_at_utc, MailOutreachSendJob.id).with_for_update().first()
    if job is None:
        db.commit()
        return None
    job.status = "claimed"
    job.lease_owner = identity
    job.lease_until_utc = now + timedelta(minutes=2)
    job.fencing_token += 1
    db.commit()
    return serialize_job(job)


def _locked_job(db, identity, job_id):
    probe = db.get(MailOutreachSendJob, job_id)
    if probe is None:
        raise not_found("任务不存在")
    binding(db, identity, probe.mailbox_binding_id)
    message = db.get(MailOutreachMessage, probe.message_id)
    db.query(CustomerAccount).filter_by(id=message.customer_id).with_for_update().one()
    mailbox = binding(db, identity, probe.mailbox_binding_id, lock=True)
    message = db.query(MailOutreachMessage).filter_by(id=message.id).populate_existing().with_for_update().one()
    db.query(CustomerContactPoint).filter_by(point_type="email", normalized_value=probe.to_email_snapshot).order_by(
        CustomerContactPoint.id).populate_existing().with_for_update().all()
    job = db.query(MailOutreachSendJob).filter_by(id=job_id).populate_existing().with_for_update().one()
    return mailbox, message, job


def _precheck(db, mailbox, message, job):
    reasons = []
    now = utc_now()
    if not get_settings().MAIL_OUTREACH_SEND_ENABLED:
        reasons.append("send_disabled")
    if not mailbox_ready(db, mailbox):
        reasons.append("mailbox_unavailable")
    allowlist = allowed_recipients()
    if "*" not in allowlist and job.to_email_snapshot.lower() not in allowlist:
        reasons.append("recipient_not_enabled")
    if job.due_at_utc < now - timedelta(minutes=policies.MAX_LATE_MINUTES):
        reasons.append("schedule_expired")
    approval = db.get(MailOutreachApproval, job.approval_id)
    revision = db.get(MailOutreachRevision, job.revision_id)
    if (approval is None or revision is None or approval.decision != "approved"
            or approval.revoked_at or message.status != "approved"
            or message.current_revision_id != job.revision_id
            or approval.revision_id != job.revision_id
            or approval.mailbox_binding_id != mailbox.id
            or approval.to_email_snapshot != job.to_email_snapshot
            or approval.to_contact_point_id != job.to_contact_point_id
            or approval.scheduled_at_utc != job.due_at_utc
            or (approval.expires_at and approval.expires_at <= beijing_now())):
        return ["approval_changed"], revision
    content_hash = policies.compute_content_sha256(
        subject=revision.subject, body_text=revision.body_text,
        language_tag=revision.language_tag, claims=revision.claims_json,
    )
    approval_hash = policies.compute_approval_sha256(
        content_sha256=content_hash, mailbox_binding_id=mailbox.id,
        to_contact_point_id=job.to_contact_point_id, to_email_snapshot=job.to_email_snapshot,
        language_tag=revision.language_tag, schedule_policy=approval.reschedule_policy_json or {},
        scheduled_at_utc=approval.scheduled_at_utc.replace(tzinfo=timezone.utc).isoformat(),
    )
    if (content_hash != revision.content_sha256 or approval_hash != approval.approval_sha256
            or not revision.subject.strip() or not revision.body_text.strip()
            or any(x.get("code") in BLOCKING_RISK_CODES for x in revision.risk_flags_json or [] if isinstance(x, dict))):
        reasons.append("approved_content_changed")
    roles, permissions = get_live_user_authorization(db, approval.approver_user_id)
    user = {"sub": str(approval.approver_user_id), "roles": roles, "permissions": permissions}
    if "super_admin" not in roles and "mail_outreach:write" not in permissions:
        reasons.append("approver_permission_revoked")
    if (mailbox.owner_user_id not in (None, approval.approver_user_id)
            and "super_admin" not in roles and "mail_outreach:admin" not in permissions):
        reasons.append("mailbox_permission_revoked")
    try:
        access = require_customer_access(db, customer_id=message.customer_id, user=user,
            action_permissions=("customer:write", "customer:admin"), manage_permissions=("customer:admin",))
        eligibility = evaluate_email_eligibility(db, access, message.customer_id,
            message.contact_id, message.contact_point_id, exclude_job_id=job.id)
        reasons.extend(eligibility["missing"])
        snapshot = build_outreach_snapshot(db, access, user=user)
        frozen = revision.evidence_snapshot_json or {}
        actual_facts = {x["fact_id"]: x["fact_fingerprint"] for x in snapshot["evidence"]}
        actual_knowledge = {x["knowledge_version_id"] for x in snapshot["knowledge_items"]}
        if (frozen.get("profile_version_id") != snapshot["current_profile_version_id"]
                or frozen.get("contact_point_id") != message.contact_point_id
                or frozen.get("email") != job.to_email_snapshot
                or any(actual_facts.get(x["fact_id"]) != x["fact_fingerprint"]
                       for x in frozen.get("fact_fingerprints", []))):
            reasons.append("evidence_changed")
        if not set(frozen.get("knowledge_version_ids", [])).issubset(actual_knowledge):
            reasons.append("knowledge_changed")
        contact = next((x for x in snapshot["contacts"] if x["contact_id"] == message.contact_id), {})
        if ((contact.get("default_language") or snapshot["default_language"]) != revision.language_tag
                or (contact.get("timezone") or snapshot["timezone"]) != revision.recipient_timezone):
            reasons.append("recipient_locale_changed")
    except CustomerAccessDenied:
        reasons.append("customer_access_revoked")
    point = db.get(CustomerContactPoint, job.to_contact_point_id)
    if point is None or point.normalized_value != job.to_email_snapshot:
        reasons.append("recipient_changed")
    try:
        local_now = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(mailbox.quota_timezone))
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
        day_end = (local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
        reservations = db.query(MailOutreachSendJob.id).filter(
            MailOutreachSendJob.mailbox_binding_id == mailbox.id,
            MailOutreachSendJob.send_started_at_utc >= day_start,
            MailOutreachSendJob.send_started_at_utc < day_end,
            MailOutreachSendJob.status.in_(("sending", "provider_accepted", "ambiguous")),
        ).with_for_update().all()
        if len(reservations) >= mailbox.daily_quota:
            reasons.append("daily_quota_exhausted")
    except (ValueError, KeyError):
        reasons.append("mailbox_timezone_invalid")
    return sorted(set(reasons)), revision


def authorize(db, identity, job_id, fence):
    mailbox, message, job = _locked_job(db, identity, job_id)
    if (job.status != "claimed" or job.send_started_at_utc is not None
            or job.fencing_token != fence or job.lease_owner != identity
            or job.lease_until_utc is None or job.lease_until_utc <= utc_now()):
        raise conflict("认领已失效或发送授权已使用", error_code="lease_invalid")
    reasons, revision = _precheck(db, mailbox, message, job)
    job.last_precheck_json = {"passed": not reasons, "reasons": reasons, "checked_at_utc": utc_now().isoformat()}
    if reasons:
        job.status = "needs_review"
        job.blocked_reason = ",".join(reasons)[:500]
        db.commit()
        raise conflict("临发复查未通过：" + job.blocked_reason, error_code="send_precheck_failed")
    job.status = "sending"
    job.send_started_at_utc = utc_now()
    job.lease_until_utc = utc_now() + timedelta(minutes=5)
    db.commit()
    return {"to": job.to_email_snapshot, "subject": revision.subject, "body_text": revision.body_text}


def record_result(db, identity, job_id, payload):
    mailbox, message, job = _locked_job(db, identity, job_id)
    if job.fencing_token != payload.fencing_token or job.lease_owner != identity:
        raise conflict("执行围栏已失效", error_code="lease_invalid")
    prior = db.query(MailOutreachSendAttempt).filter_by(job_id=job.id, fencing_token=payload.fencing_token).first()
    if prior:
        if prior.outcome != payload.outcome or prior.provider_message_id != payload.provider_message_id:
            raise conflict("发送结果与已记录结果冲突", error_code="result_conflict")
        return serialize_job(job)
    before_send = job.send_started_at_utc is None and job.status in ("claimed", "needs_review", "cancelled")
    if payload.outcome == "accepted" and (job.status not in ("sending", "ambiguous") or job.send_started_at_utc is None):
        raise conflict("任务尚未获得发送授权", error_code="send_not_authorized")
    if not before_send and job.status not in ("sending", "ambiguous"):
        raise conflict("任务状态不接受发送结果", error_code="send_not_authorized")
    db.add(MailOutreachSendAttempt(job_id=job.id, fencing_token=payload.fencing_token,
        outcome=payload.outcome, provider_message_id=payload.provider_message_id,
        error_kind=payload.error_kind, precheck_result_json=job.last_precheck_json,
        provider_response_redacted={"queued": payload.outcome == "accepted"},
        started_at_utc=job.send_started_at_utc, finished_at_utc=utc_now()))
    if not (before_send and job.status in ("needs_review", "cancelled")):
        job.status = {"accepted": "provider_accepted", "failed_safe": "failed_safe", "unknown": "ambiguous"}[payload.outcome]
        if job.status == "ambiguous" and job.send_started_at_utc is None:
            job.send_started_at_utc = utc_now()
    if payload.outcome == "accepted":
        message.status = "completed"
        from app.mail_outreach.event_service import append_timeline
        append_timeline(db, message.customer_id, "outreach.accepted", job.id,
                        "开发信已获邮件通道接受", {"job_id": job.id})
    db.commit()
    return serialize_job(job)
