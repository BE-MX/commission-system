"""Transactional notification fan-out and leased mail delivery, outside DB transactions."""
import logging
import secrets
import smtplib
from datetime import timedelta
from app.portal.configuration import employee_origin

from sqlalchemy import and_, or_, select

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal import admin_service, mapping_notifications, order_queries
from app.portal.access_policy import customer_principal, validate_binding
from app.portal.auth_service import enabled_site
from app.portal.authority import lock_authority
from app.portal.domain import normalize_email
from app.portal.errors import PortalError, reject
from app.portal.mail_worker import Mail, MAX_ATTEMPTS, LEASE_SECONDS, RETRY_MINUTES, close_event, leased_event, smtp_sender
from app.portal.models import Account, CustomerAccess, Membership, OrderRequest, OutboxEvent

logger = logging.getLogger(__name__)
STAFF_EVENTS = {'order_submitted', 'order_cancelled', 'order_accepted', 'order_proposal_rejected', 'pi_accepted', 'pi_rejected'}
CUSTOMER_EVENTS = {'order_proposed', 'order_rejected', 'order_invoice_created', 'pi_proposed', 'pi_published', 'order_pi_voided'}
BUSINESS_EVENTS = STAFF_EVENTS | CUSTOMER_EVENTS
MAIL_EVENT = 'business_mail'
DELIVERY_EVENTS = BUSINESS_EVENTS | {MAIL_EVENT} | mapping_notifications.EVENTS
LABELS = {
    'order_submitted': ('客户提交了下单请求', 'A request was submitted'),
    'order_cancelled': ('客户取消了下单请求', 'A request was cancelled'),
    'order_accepted': ('客户接受了提案', 'A proposal was accepted'),
    'order_proposal_rejected': ('客户拒绝了提案', 'A proposal was declined'),
    'order_proposed': ('业务员发送了提案', 'A proposal was issued'),
    'order_rejected': ('业务员拒绝了下单请求', 'A request was declined'),
    'order_invoice_created': ('正式 PI 已生成', 'A pro forma invoice was issued'),
    'pi_proposed': ('PI 修改提案已发送', 'A PI amendment proposal was issued'),
    'pi_accepted': ('客户接受了 PI 修改提案', 'A PI amendment was accepted'),
    'pi_rejected': ('客户拒绝了 PI 修改提案', 'A PI amendment was declined'),
    'pi_published': ('已确认的 PI 已发布', 'A confirmed PI was published'),
    'order_pi_voided': ('PI 已作废', 'A PI was voided'),
}


def claim(db):
    lock_authority(db, force=True)
    now = beijing_now()
    row = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type.in_(DELIVERY_EVENTS), or_(
        and_(OutboxEvent.status == 'pending', OutboxEvent.next_attempt_at <= now),
        and_(OutboxEvent.status == 'sending', OutboxEvent.lease_until <= now)))
        .order_by(OutboxEvent.next_attempt_at, OutboxEvent.id).limit(1).with_for_update())
    if row is None:
        return None
    if row.attempt_count >= MAX_ATTEMPTS:
        close_event(row, 'dead', 'ATTEMPTS_EXHAUSTED')
        return None
    row.status, row.attempt_count = 'sending', row.attempt_count + 1
    row.lease_token, row.lease_until = secrets.token_hex(32), now + timedelta(seconds=LEASE_SECONDS)
    db.flush()
    return row.public_id, row.lease_token


def scoped_order(db, row):
    site = enabled_site(db)
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == row.aggregate_public_id)
        .execution_options(populate_existing=True))
    access = db.get(CustomerAccess, order.access_id, populate_existing=True) if order else None
    if order is None or access is None or access.site_id != site.id or row.payload_json.get('request_id') != order.public_id:
        reject('NOTIFICATION_OBJECT_INVALID', 'Notification object is not available.', 404)
    validate_binding(db, access)
    if access.status != 'enabled':
        reject('AUTHORIZATION_CHANGED', 'Customer access is not enabled.', 403)
    return site, access, order


def expand(db, row):
    """Fan-out is atomic; event-key uniqueness makes worker retries safe."""
    site, access, order = scoped_order(db, row)
    targets = [('staff', None)] if row.event_type in STAFF_EVENTS else [
        ('customer', member.id) for member in db.scalars(select(Membership).join(Account, Account.id == Membership.account_id)
            .where(Membership.access_id == access.id, Membership.site_id == site.id,
                Membership.status == 'active', Account.status == 'active', Account.verified_at.is_not(None))
            .order_by(Membership.id)).all()]
    for kind, member_id in targets:
        key = f'notify:{row.public_id}:{kind}:{member_id or "current"}'
        if db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_key == key)) is not None:
            continue
        db.add(OutboxEvent(event_key=key, event_type=MAIL_EVENT, aggregate_public_id=order.public_id,
            payload_json={'request_id': order.public_id, 'source_event_id': row.public_id,
                'recipient_kind': kind, 'membership_id': str(member_id) if member_id else None}, next_attempt_at=beijing_now()))
    close_event(row, 'expanded' if targets else 'cancelled', None if targets else 'NO_ACTIVE_RECIPIENT')
    db.flush()


def prepare(db, public_id, lease):
    row = leased_event(db, public_id, lease)
    if row is None or row.event_type not in DELIVERY_EVENTS:
        return None
    if row.event_type in mapping_notifications.EVENTS:
        return mapping_notifications.prepare(db, row)
    try:
        if row.event_type in BUSINESS_EVENTS:
            expand(db, row)
            return None
        site, access, order = scoped_order(db, row)
        source = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == row.payload_json.get('source_event_id')))
        if source is None or source.event_type not in BUSINESS_EVENTS or source.aggregate_public_id != order.public_id or source.payload_json.get('request_id') != order.public_id or source.status != 'expanded':
            close_event(row, 'dead', 'NOTIFICATION_SOURCE_INVALID')
            return None
        if row.payload_json.get('recipient_kind') == 'staff' and source.event_type in STAFF_EVENTS:
            # Delayed delivery resolves the CURRENT owner, never the enqueue-time owner.
            user = db.get(ArkUser, access.sales_user_id, populate_existing=True)
            if user is None or not user.is_active or user.deleted_at is not None:
                reject('AUTHORIZATION_CHANGED', 'Employee unavailable.', 403)
            actor = admin_service.employee_principal(db, user.id, 'portal_order:read')
            if db.scalar(order_queries.employee_query(db, actor).where(OrderRequest.id == order.id)) is None:
                reject('AUTHORIZATION_CHANGED', 'Order outside current scope.', 403)
            recipient = normalize_email(user.email or '')
            link = employee_origin(get_settings()) + '/portal/orders?request=' + order.public_id
            subject = 'LeShine 方舟 · 客户请求动态'
            body = f'{LABELS[source.event_type][0]}。\n请求号：{order.public_no}\n\n请登录方舟查看最新状态与权限允许的操作：\n{link}\n\n通知不代表锁货、收款或新的审批授权。'
        elif row.payload_json.get('recipient_kind') == 'customer' and source.event_type in CUSTOMER_EVENTS:
            member = db.get(Membership, int(row.payload_json['membership_id']), populate_existing=True)
            if member is None or member.access_id != access.id or member.site_id != site.id:
                reject('AUTHORIZATION_CHANGED', 'Membership unavailable.', 403)
            principal = customer_principal(db, member.account_id, member.id)
            if principal.account.verified_at is None:
                reject('AUTHORIZATION_CHANGED', 'Verified mailbox required.', 403)
            principal.require('order_status')
            recipient = principal.account.email_normalized
            link = site.allowed_origin + '/orders/' + order.public_id
            subject = 'LeShine · Request update'
            body = f'{LABELS[source.event_type][1]}.\nRequest: {order.public_no}\n\nSign in to review the latest status and complete terms:\n{link}\n\nThis notification does not reserve stock or confirm payment. Always review the current request in the portal.'
        else:
            close_event(row, 'dead', 'NOTIFICATION_RECIPIENT_INVALID')
            return None
    except PortalError as error:
        if error.status >= 500:
            raise
        close_event(row, 'dead' if error.code == 'INVALID_INPUT' else 'cancelled',
                    'NOTIFICATION_RECIPIENT_INVALID' if error.code == 'INVALID_INPUT' else 'AUTHORIZATION_CHANGED')
        return None
    return Mail(recipient, subject, body, f'<portal-{row.public_id}@leshine.invalid>', row.lease_until)


def finish(db, public_id, lease, *, outcome, error=None):
    row = leased_event(db, public_id, lease)
    if row is None:
        return 'lease_lost'
    if outcome in {'sent', 'cancelled'}:
        close_event(row, outcome, error)
    elif row.attempt_count >= MAX_ATTEMPTS:
        close_event(row, 'dead', error)
    else:
        row.status, row.last_error_code = 'pending', error
        row.next_attempt_at = beijing_now() + timedelta(minutes=RETRY_MINUTES[row.attempt_count - 1])
        row.lease_token = row.lease_until = None
    return row.status


def run_once(session_factory, sender=None):
    settings = get_settings()
    if not (settings.PORTAL_ENABLED and settings.PORTAL_MAIL_ENABLED and settings.PORTAL_NOTIFICATION_ENABLED):
        return 'disabled'
    with session_factory() as db:
        leased = claim(db)
        db.commit()
    if leased is None:
        return 'idle'
    public_id, lease = leased
    try:
        with session_factory() as db:
            mail = prepare(db, public_id, lease)
            row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == public_id))
            status = row.status if row else 'lease_lost'
            db.commit()
        if mail is None:
            return status
        delivered = (sender or smtp_sender)(mail)
        outcome, error = ('sent', None) if delivered is True else ('retry', 'LEASE_EXPIRED_BEFORE_SEND')
    except PortalError:
        outcome, error = 'retry', 'AUTHORITY_UNAVAILABLE'
    except (ValueError, TypeError, KeyError):
        outcome, error = 'retry', 'NOTIFICATION_CONFIGURATION_INVALID'
    except (smtplib.SMTPException, OSError):
        outcome, error = 'retry', 'MAIL_TRANSPORT_FAILED'
    if error:
        logger.warning('Portal notification attempt failed: %s', error)
        print(f'Portal notification attempt failed: {error}', flush=True)
    with session_factory() as db:
        status = finish(db, public_id, lease, outcome=outcome, error=error)
        db.commit()
    return status
