"""Customer-scoped mapping delivery history and controlled recovery."""
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.portal import admin_service as admin, mapping_notifications as mapping, notification_admin_service as delivery
from app.portal.errors import reject
from app.portal.models import MappingRevision, OutboxEvent


def scoped_query(access):
    source = aliased(OutboxEvent)
    child_source = select(source.id).where(source.public_id == OutboxEvent.payload_json['source_event_id'].as_string(),
        source.event_type == mapping.SOURCE_EVENT, source.aggregate_public_id == access.public_id,
        source.payload_json['access_public_id'].as_string() == access.public_id,
        source.payload_json['mapping_revision_public_id'].as_string() == MappingRevision.public_id,
        source.payload_json['mapping_version'].as_integer() == MappingRevision.version)
    return select(OutboxEvent).join(MappingRevision,
        MappingRevision.public_id == OutboxEvent.payload_json['mapping_revision_public_id'].as_string()).where(
        OutboxEvent.aggregate_public_id == access.public_id,
        OutboxEvent.payload_json['access_public_id'].as_string() == access.public_id,
        OutboxEvent.event_type.in_(mapping.EVENTS), MappingRevision.access_id == access.id,
        or_(and_(OutboxEvent.event_type == mapping.SOURCE_EVENT,
                 OutboxEvent.payload_json['mapping_version'].as_integer() == MappingRevision.version),
            and_(OutboxEvent.event_type == mapping.MAIL_EVENT, child_source.exists())))


def list_events(db, actor_id, access_id, *, page=1, page_size=20):
    actor = admin.begin(db, actor_id, 'portal_mapping:read')
    access = admin.scoped_access(db, access_id, actor)
    query = scoped_query(access)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(OutboxEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {'access_id': access.public_id, 'items': [delivery.event_view(row) for row in rows],
            'total': total, 'page': page, 'page_size': page_size}


def retry(db, actor_id, access_id, event_id, command_key, body):
    actor = admin.begin(db, actor_id, 'portal_mapping:write')
    access = admin.scoped_access(db, access_id, actor)
    reader = admin.employee_principal(db, actor_id, 'portal_mapping:read')
    admin.scoped_access(db, access_id, reader)
    row = db.scalar(scoped_query(access).where(OutboxEvent.public_id == str(event_id)).with_for_update()
        .execution_options(populate_existing=True))
    if row is None:
        reject('RESOURCE_NOT_FOUND', '映射通知不存在或不在当前授权范围内。', 404)
    return delivery.requeue(db, actor_id, access, row, command_key, body,
                            scope={'access_id': access.public_id}, validate=mapping.validate_recovery)
