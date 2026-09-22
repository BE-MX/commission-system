"""Post-commit recharge/adjustment reminders to currently authorized reviewers."""
import asyncio
import logging
from sqlalchemy import or_
from app.auth.models import ArkUser, ArkRole, ArkPermission
from app.core.config import get_settings
from app.dingtalk.work_notify import get_work_notifier
from app.domestic.request_service import pending_request_count

logger = logging.getLogger(__name__)


def reviewer_ids(db, applicant_id):
    admin_role = or_(ArkRole.name == 'super_admin',
                    ArkRole.permissions.any(ArkPermission.code == 'domestic:admin'))
    reviewer_role = ArkRole.permissions.any(ArkPermission.code == 'domestic:review')
    rows = db.query(ArkUser.dingtalk_id).filter(
        ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
        ArkUser.dingtalk_id.isnot(None),
        ArkUser.roles.any(or_(admin_role, reviewer_role)),
        # Reviewers cannot approve their own request; administrators can.
        or_(ArkUser.id != applicant_id, ArkUser.roles.any(admin_role)),
    ).all()
    return sorted({value.strip() for (value,) in rows if value and value.strip()})


async def notify_submitted(db, result):
    # The request service has already committed. Replays are never new events.
    if result.get('replayed') or result.get('status') != 'pending':
        return
    try:
        with db.begin_nested():
            recipients = reviewer_ids(db, result['created_by'])
            count = pending_request_count(db, viewer_user_id=result['created_by'], can_review_all=True)
        if not recipients:
            logger.warning('Domestic review notice skipped: no bound reviewers request=%s', result['id'])
            print(f"[DOMESTIC] no bound reviewers request={result['id']}", flush=True)
            return
        kind = '充值' if result['request_type'] == 'recharge' else '调整'
        url = get_settings().DOMESTIC_REVIEW_NOTICE_BASE_URL.rstrip('/') + '/domestic/customer-requests'
        sent = await asyncio.wait_for(get_work_notifier().send_oa_notice(
            recipients, '充值调整待审核',
            f"有新的{kind}申请（#{result['id']}）待审核，当前共 {count} 笔待审核申请，请及时处理。",
            url,
        ), timeout=10)
        if not sent:
            logger.warning('Domestic review notice failed: request=%s', result['id'])
            print(f"[DOMESTIC] notice failed request={result['id']}", flush=True)
    except Exception as exc:
        logger.warning('Domestic review notice failed: request=%s type=%s', result['id'], type(exc).__name__)
        print(f"[DOMESTIC] notice failed request={result['id']} type={type(exc).__name__}", flush=True)
