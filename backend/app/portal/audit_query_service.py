"""Order-scoped employee audit projection; never expose arbitrary stored JSON."""
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from app.portal import admin_service as admin, order_queries
from app.portal.errors import reject
from app.portal.notification_admin_service import EVENTS
from app.portal.models import AuditEvent, Conversion, OrderRequest, OutboxEvent


def safe_changes(value):
    result = {}
    if not isinstance(value, dict):
        return result
    for key in ('line_count', 'invoice_id', 'employee_id', 'publication_count'):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 2**63 - 1:
            result[key] = item
    for key in ('revision_id', 'publication_id'):
        item = value.get(key)
        if isinstance(item, str):
            try:
                result[key] = str(UUID(item))
            except ValueError:
                # Untrusted or legacy audit data is omitted, not interpreted.
                continue
    for key in ('status', 'invoice_status'):
        if value.get(key) in ('submitted', 'awaiting_customer', 'accepted', 'rejected',
                              'cancelled', 'invoice_created', 'draft', 'pending'):
            result[key] = value[key]
    return result


def list_events(db, actor_id, public_id, *, page=1, page_size=20):
    actor = admin.begin(db, actor_id, 'portal_order:read')
    order = db.scalar(order_queries.employee_query(db, actor).where(OrderRequest.public_id == str(public_id)))
    if order is None:
        reject('RESOURCE_NOT_FOUND', '请求不存在或不在当前授权范围内。', 404)
    # Bind related objects through persisted lineage, never a JSON request_id claim.
    conversions = select(Conversion.public_id).where(Conversion.request_id == order.id)
    notifications = select(OutboxEvent.public_id).where(OutboxEvent.aggregate_public_id == order.public_id,
        OutboxEvent.event_type.in_(EVENTS))
    query = select(AuditEvent).where(
        or_(AuditEvent.access_id == order.access_id, AuditEvent.access_id.is_(None)),
        or_(and_(AuditEvent.object_type == 'order_request', AuditEvent.object_public_id == order.public_id),
            and_(AuditEvent.object_type == 'invoice', AuditEvent.object_public_id.in_(conversions)),
            and_(AuditEvent.object_type == 'notification', AuditEvent.object_public_id.in_(notifications))))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {'request_id': order.public_id, 'total': total, 'page': page, 'page_size': page_size,
        'items': [{'id': row.public_id, 'actor_type': row.actor_type, 'actor_id': row.actor_id,
            'object_type': row.object_type, 'object_id': row.object_public_id, 'action': row.action,
            'created_at': row.created_at.isoformat(), 'before_version': row.before_version,
            'after_version': row.after_version, 'reason': row.reason, 'trace_id': row.trace_id,
            'changes': safe_changes(row.safe_diff_json)} for row in rows]}
