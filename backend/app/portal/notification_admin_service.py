"""Scoped business-delivery inspection and idempotent, audited retry requests."""
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select

from app.core.time import beijing_now
from app.portal import admin_service as admin, notification_worker as worker, order_queries, proposal_service
from app.portal.domain import content_hash
from app.portal.errors import reject
from app.portal.models import AuditEvent, CommandReceipt, OrderRequest, OutboxEvent

EVENTS = worker.BUSINESS_EVENTS | {worker.MAIL_EVENT}
RETRY_ERRORS = {'MAIL_TRANSPORT_FAILED', 'AUTHORITY_UNAVAILABLE', 'NOTIFICATION_CONFIGURATION_INVALID',
                'LEASE_EXPIRED_BEFORE_SEND', 'ATTEMPTS_EXHAUSTED'}
SAFE_ERRORS = RETRY_ERRORS | {'AUTHORIZATION_CHANGED', 'NOTIFICATION_OBJECT_INVALID', 'NO_ACTIVE_RECIPIENT',
                            'NOTIFICATION_SOURCE_INVALID', 'NOTIFICATION_RECIPIENT_INVALID', 'NOTIFICATION_SUPERSEDED'}


def fingerprint(row):
    return content_hash({'id': row.public_id, 'status': row.status, 'attempt_count': row.attempt_count,
        'next_attempt_at': row.next_attempt_at.isoformat(), 'error': row.last_error_code,
        'lease_until': row.lease_until.isoformat() if row.lease_until else None})


def recoverable(row):
    return row.status == 'dead' and row.last_error_code in RETRY_ERRORS


def event_view(row):
    return {'id': row.public_id, 'event_type': row.event_type, 'status': row.status,
        'recipient_kind': row.payload_json.get('recipient_kind') if row.event_type in {worker.MAIL_EVENT, worker.mapping_notifications.MAIL_EVENT} else None,
        'attempt_count': row.attempt_count, 'created_at': row.created_at.isoformat(),
        'next_attempt_at': row.next_attempt_at.isoformat() if row.status == 'pending' else None,
        'lease_until': row.lease_until.isoformat() if row.lease_until else None,
        'error_code': row.last_error_code if row.last_error_code in SAFE_ERRORS else 'DELIVERY_FAILED' if row.last_error_code else None,
        'retry_eligible': recoverable(row), 'fingerprint': fingerprint(row)}


def scoped_query(order):
    # Authentication events are excluded even if their aggregate ID were corrupted.
    return select(OutboxEvent).where(OutboxEvent.aggregate_public_id == order.public_id,
                                    OutboxEvent.event_type.in_(EVENTS))


def list_events(db, actor_id, public_id, *, page=1, page_size=20):
    actor = admin.begin(db, actor_id, 'portal_order:read')
    order = db.scalar(order_queries.employee_query(db, actor).where(OrderRequest.public_id == str(public_id)))
    if order is None:
        reject('RESOURCE_NOT_FOUND', '请求不存在或不在当前授权范围内。', 404)
    query = scoped_query(order)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(OutboxEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {'request_id': order.public_id, 'items': [event_view(row) for row in rows],
            'total': total, 'page': page, 'page_size': page_size}


def retry(db, actor_id, public_id, event_id, command_key, body):
    # Read-all alone grants no write scope. Fresh owner/delegation and binding are mandatory.
    actor, site, access, order = proposal_service.managed_request(db, actor_id, public_id)
    reader = admin.employee_principal(db, actor_id, 'portal_order:read')
    if db.scalar(order_queries.employee_query(db, reader).where(OrderRequest.id == order.id)) is None:
        reject('RESOURCE_NOT_FOUND', '请求不存在或不在当前授权范围内。', 404)
    row = db.scalar(scoped_query(order).where(OutboxEvent.public_id == str(event_id))
        .with_for_update().execution_options(populate_existing=True))
    if row is None:
        reject('RESOURCE_NOT_FOUND', '业务通知不存在或不在当前授权范围内。', 404)
    return requeue(db, actor_id, access, row, command_key, body,
                   scope={'request_id': order.public_id}, validate=worker.scoped_order)


def requeue(db, actor_id, access, row, command_key, body, *, scope, validate):
    # Caller establishes current read/write scope before entering this command.
    digest = content_hash(body.model_dump(mode='json'))
    saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action == 'notification_retry',
        CommandReceipt.object_public_id == row.public_id, CommandReceipt.command_key == str(command_key)))
    if saved is not None:
        if saved.payload_hash != digest:
            reject('IDEMPOTENCY_CONFLICT', '原重试命令内容不能更改。', 409)
        return {'replayed': True, 'original_receipt': deepcopy(saved.result_reference_json), 'current': event_view(row)}
    settings = worker.get_settings()
    if not (settings.PORTAL_MAIL_ENABLED and settings.PORTAL_NOTIFICATION_ENABLED):
        reject('NOTIFICATION_DISABLED', '业务通知尚未启用，请先完成邮件配置。', 409)
    validate(db, row)
    if body.fingerprint != fingerprint(row):
        reject('VERSION_CONFLICT', '投递状态已变化，请刷新后确认。', 409)
    if not recoverable(row):
        reject('NOTIFICATION_NOT_RETRYABLE', '此通知不能人工重试；已发送、已取消或正在处理的任务不可重发。', 409)
    previous = {'status': row.status, 'attempt_count': row.attempt_count, 'error_code': row.last_error_code}
    row.status, row.attempt_count, row.last_error_code = 'pending', 0, None
    row.next_attempt_at = beijing_now()
    row.lease_token = row.lease_until = None
    receipt = {**scope, 'event_id': row.public_id,
               'command_key': str(command_key), 'status': 'pending'}
    db.add(CommandReceipt(action='notification_retry', object_public_id=row.public_id, command_key=str(command_key),
        payload_hash=digest, result_reference_json=receipt, first_actor_type='employee', first_actor_id=int(actor_id),
        completed_at=beijing_now()))
    db.add(AuditEvent(actor_type='employee', actor_id=int(actor_id), access_id=access.id, object_type='notification',
        object_public_id=row.public_id, action='notification.retry_requested', reason=body.reason,
        safe_diff_json={'previous': previous, 'status': 'pending', **scope}, trace_id=str(uuid4())))
    db.flush()
    return {'replayed': False, 'original_receipt': receipt, 'current': event_view(row)}
