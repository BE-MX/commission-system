"""Post-commit notices using the live OKKI customer owners, never order history."""
import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from urllib.parse import urlencode
from app.core.config import get_settings
from app.auth.models import ArkUser, ArkUserExternalBinding
from app.core.time import to_beijing_naive
from app.invoice.models import InvoiceCustomerOverlay
from app.dingtalk.work_notify import get_work_notifier
from app.shipping_inspection import outbound_service
from app.shipping_inspection.models import ShippingInspection

logger = logging.getLogger(__name__)


def source_time(value):
    if not value:
        return None
    try:
        raw = str(value).strip()
        parsed = datetime.fromtimestamp(int(raw), timezone.utc) if raw.isdigit() else datetime.fromisoformat(raw)
        return to_beijing_naive(parsed)
    except (ValueError, OverflowError, OSError):
        return None


def current_salespeople(db, outbound_record_id):
    rm = outbound_service._record_columns(db)
    if not rm.get('company_id'):
        return []
    schema = outbound_service._schema()
    company_id = db.execute(text(
        f"SELECT `{rm['company_id']}` FROM `{schema}`."
        f"`{outbound_service.RECORDS_TABLE}` WHERE `{rm['id']}` = :rid"
    ), {'rid': outbound_record_id}).scalar_one_or_none()
    if company_id is None:
        return []
    # Both sources belong to the same configured OKKI mirror, not global identities.
    mirror = db.execute(text(f"SELECT owner_user_ids, update_time FROM `{schema}`.customer_info WHERE company_id = :cid"),
                        {'cid': str(company_id)}).mappings().one_or_none()
    overlay = db.get(InvoiceCustomerOverlay, str(company_id))
    raw = mirror['owner_user_ids'] if mirror else []
    if overlay is not None:
        mirror_time = source_time(mirror['update_time']) if mirror else None
        overlay_time = source_time(overlay.source_update_time)
        # Same precedence as invoice customer selection: unknown times favor manual sync.
        if not (mirror_time and overlay_time and mirror_time >= overlay_time):
            raw = overlay.owner_user_ids
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    owner_ids = {str(value).strip() for value in raw if not isinstance(value, bool) and str(value).strip().isdigit()}
    users = {}
    for external_id in owner_ids:
        matches = db.query(ArkUser).join(ArkUserExternalBinding, ArkUserExternalBinding.ark_user_id == ArkUser.id).filter(
            ArkUserExternalBinding.provider == 'okki',
            ArkUserExternalBinding.external_account_id == external_id,
            ArkUserExternalBinding.binding_status == 'active',
            ArkUserExternalBinding.deleted_at.is_(None),
            ArkUser.deleted_at.is_(None),
        ).all()
        if len(matches) != 1:
            return []  # Ambiguous or missing binding: never guess the responsible user.
        user = matches[0]
        if user.is_active and (user.dingtalk_id or '').strip():
            users[user.id] = user
    return list(users.values())


async def notify_submitted(db, submitted_ids):
    """Only successful state transitions supply IDs; replays never send again.

    The caller has committed. Notification problems cannot undo that commit.
    No automatic resend after an uncertain provider response (duplicate risk).
    """
    for inspection_id in submitted_ids:
        try:
            with db.begin_nested():
                inspection = db.get(ShippingInspection, inspection_id)
                users = current_salespeople(db, inspection.outbound_record_id)
            if not users:
                logger.warning('Inspection notification skipped: inspection=%s, current owner or DingTalk binding missing', inspection_id)
                print(f'[SHIPPING] notification skipped: inspection={inspection_id}, current owner or DingTalk binding missing', flush=True)
                continue
            content = f'客户【{inspection.customer_name or "未命名客户"}】的【{inspection.outbound_no}】出库单已出库检验完成，请及时验货。'
            url = get_settings().SHIPPING_INSPECTION_NOTICE_BASE_URL.rstrip('/') + '/shipping/inspections?' + urlencode({
                'pdf': inspection.id, 'version': inspection.edit_version, 'keyword': inspection.outbound_no,
            })
            content += ' 点击本通知下载验货单 PDF（含验货照片）。'
            sent = await asyncio.wait_for(get_work_notifier().send_oa_notice(
                sorted({user.dingtalk_id.strip() for user in users}), '出库检验完成', content, url), timeout=10)
            if not sent:
                logger.warning('Inspection notification failed: inspection=%s', inspection_id)
                print(f'[SHIPPING] notification failed: inspection={inspection_id}', flush=True)
        except Exception as exc:
            # Do not print provider exception text: it may contain request credentials.
            logger.warning('Inspection notification failed: inspection=%s type=%s', inspection_id, type(exc).__name__)
            print(f'[SHIPPING] notification failed: inspection={inspection_id} type={type(exc).__name__}', flush=True)
