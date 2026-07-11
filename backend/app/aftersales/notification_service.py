"""售后钉钉通知 outbox、幂等发送和重试。"""

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.aftersales.models import (
    AfterSalesCase,
    AfterSalesNotificationLog,
)
from app.auth.models import ArkUser
from app.dingtalk.work_notify import get_work_notifier


logger = logging.getLogger("commission.aftersales.notification")
MAX_AUTO_ATTEMPTS = 3


def _sanitize_error(error: Exception) -> str:
    message = str(error)
    message = re.sub(
        r"(?i)(token|secret|password|key)\s*[=:]\s*[^\s,;]+",
        r"\1=[redacted]",
        message,
    )
    return message[:500]


def enqueue_notification(
    db: Session,
    case: AfterSalesCase,
    business_event_key: str,
    recipient: ArkUser,
    template_code: str,
    payload: dict,
) -> AfterSalesNotificationLog:
    existing = (
        db.query(AfterSalesNotificationLog)
        .filter(
            AfterSalesNotificationLog.business_event_key == business_event_key,
            AfterSalesNotificationLog.recipient_user_id == recipient.id,
        )
        .first()
    )
    if existing:
        return existing
    log = AfterSalesNotificationLog(
        case_id=case.id,
        business_event_key=business_event_key,
        recipient_user_id=recipient.id,
        recipient_dingtalk_id=recipient.dingtalk_id,
        template_code=template_code,
        payload_json=payload,
        status="pending" if recipient.dingtalk_id else "failed",
        next_retry_at=None if recipient.dingtalk_id else datetime.utcnow() + timedelta(seconds=60),
        last_error_summary=None if recipient.dingtalk_id else "通知接收人尚未绑定钉钉账号",
    )
    db.add(log)
    db.flush()
    return log


async def deliver_notification(
    db: Session,
    notification_id: int,
    *,
    notifier=None,
    manual: bool = False,
) -> AfterSalesNotificationLog:
    log = (
        db.query(AfterSalesNotificationLog)
        .filter(AfterSalesNotificationLog.id == notification_id)
        .with_for_update()
        .first()
    )
    if log is None:
        raise ValueError("通知记录不存在")
    if log.status == "success":
        return log
    if log.attempt_count >= MAX_AUTO_ATTEMPTS and not manual:
        return log

    log.attempt_count += 1
    payload = log.payload_json or {}
    try:
        recipient = db.get(ArkUser, log.recipient_user_id)
        current_dingtalk_id = recipient.dingtalk_id if recipient else None
        if not current_dingtalk_id:
            raise RuntimeError("通知接收人尚未绑定钉钉账号")
        log.recipient_dingtalk_id = current_dingtalk_id
        notifier = notifier or get_work_notifier()
        sent = await notifier.send_oa_notice(
            user_ids=[current_dingtalk_id],
            title=payload.get("title") or "售后流程通知",
            content=payload.get("content") or "请进入方舟平台查看详情。",
            message_url=payload.get("message_url") or "",
        )
        if sent is False:
            raise RuntimeError("DingTalk notifier returned failure")
        log.status = "success"
        log.sent_at = datetime.utcnow()
        log.next_retry_at = None
        log.last_error_summary = None
    except Exception as exc:
        summary = _sanitize_error(exc)
        log.status = "failed"
        log.last_error_summary = summary
        log.next_retry_at = datetime.utcnow() + timedelta(
            seconds=60 * (2 ** (log.attempt_count - 1))
        )
        logger.warning("售后通知发送失败 notification_id=%s: %s", log.id, summary)
        print(
            f"[AFTERSALES] notification failed id={log.id}: {summary}",
            flush=True,
        )
    db.commit()
    db.refresh(log)
    return log


async def process_due_notifications(
    db: Session,
    *,
    notifier=None,
    batch_size: int = 50,
) -> int:
    """发送因进程退出遗留的 pending 通知及到期失败通知。"""
    now = datetime.utcnow()
    notification_ids = [
        item[0]
        for item in (
            db.query(AfterSalesNotificationLog.id)
            .filter(
                AfterSalesNotificationLog.attempt_count < MAX_AUTO_ATTEMPTS,
                or_(
                    AfterSalesNotificationLog.status == "pending",
                    (
                        (AfterSalesNotificationLog.status == "failed")
                        & (AfterSalesNotificationLog.next_retry_at <= now)
                    ),
                ),
            )
            .order_by(AfterSalesNotificationLog.created_at, AfterSalesNotificationLog.id)
            .limit(batch_size)
            .all()
        )
    ]
    for notification_id in notification_ids:
        await deliver_notification(db, notification_id, notifier=notifier)
    return len(notification_ids)
