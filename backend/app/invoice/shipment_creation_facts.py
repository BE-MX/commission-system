"""Immutable late creation results and employee recovery evidence."""
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import event, inspect, select

from app.invoice.cancellation_facts import digest
from app.portal.event_models import AuditEvent

PREFIX = 'shipment_create_'
LATE = PREFIX + 'late_result'
RECOVERED = PREFIX + 'recovered'


def object_id(target_id):
    return str(uuid5(NAMESPACE_URL, f'leshine:shipment-create:{target_id}'))


@event.listens_for(AuditEvent, 'before_update')
@event.listens_for(AuditEvent, 'before_delete')
def immutable(mapper, connection, row):
    state = inspect(row)
    actions = {row.action, *state.attrs.action.history.deleted}
    if state.identity:
        actions.add(connection.scalar(select(AuditEvent.action).where(AuditEvent.id == state.identity[0])))
    if any(str(value).startswith(PREFIX) for value in actions):
        raise ValueError('Original shipment creation evidence is immutable')


def rows(db, target_id, *, current=False):
    query = select(AuditEvent).where(AuditEvent.object_type == 'shipment_outbound_create',
        AuditEvent.object_public_id == object_id(target_id)).order_by(AuditEvent.id)
    if current:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalars(query).all()


def late_results(db, target_id, *, current=False):
    return [row for row in rows(db, target_id, current=current) if row.action == LATE]


def fingerprint(db, target_id, *, current=False):
    return digest([[getattr(row, column.name) for column in AuditEvent.__table__.columns]
        for row in rows(db, target_id, current=current)])


def append(db, target_id, action, key, data, *, actor_id=None, reason=''):
    identity = str(uuid5(NAMESPACE_URL, f'leshine:shipment-create:{target_id}:{action}:{key}'))
    existing = db.scalar(select(AuditEvent).where(AuditEvent.public_id == identity).with_for_update()
        .execution_options(populate_existing=True))
    if existing:
        if (existing.action != action or existing.object_type != 'shipment_outbound_create'
                or existing.object_public_id != object_id(target_id) or existing.safe_diff_json != data):
            raise ValueError('Original shipment creation evidence changed')
        return existing
    row = AuditEvent(public_id=identity, actor_type='employee' if actor_id else 'system', actor_id=actor_id,
        object_type='shipment_outbound_create', object_public_id=object_id(target_id), action=action,
        trace_id=key, reason=reason, safe_diff_json=data)
    db.add(row)
    db.flush()
    return row


def remember_late_result(db, target, attempt_token, remote_id):
    key = digest([attempt_token, str(remote_id)])
    data = {'target_id': target.id, 'invoice_id': target.invoice_id, 'settlement_id': target.settlement_id,
        'attempt_token': attempt_token, 'remote_id': str(remote_id), 'serial_id': target.outbound_no,
        'payload_hash': target.payload_hash}
    return append(db, target.id, LATE, key, data)
