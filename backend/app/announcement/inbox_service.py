"""Reader inbox: only current, visible publications and per-user versioned reads."""
import logging

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.time import beijing_now
from app.announcement import service
from app.announcement.models import Announcement, AnnouncementConfig, AnnouncementMeta, AnnouncementRead
from app.knowledge import access, service as knowledge
from app.knowledge.models import KnowledgeDocument, KnowledgeRevision

logger = logging.getLogger(__name__)


def _query(db, identity, *, lock=False):
    service.require(identity, 'read')
    if db.get(AnnouncementConfig, 1) is None:
        return None
    config = service.config_for(db, identity, lock=lock)
    now = beijing_now()
    query = db.query(Announcement, KnowledgeDocument, KnowledgeRevision, AnnouncementMeta).join(
        KnowledgeDocument, KnowledgeDocument.id == Announcement.document_id,
    ).join(KnowledgeRevision, KnowledgeRevision.id == KnowledgeDocument.published_revision_id).join(
        AnnouncementMeta, AnnouncementMeta.revision_id == KnowledgeRevision.id,
    ).filter(
        KnowledgeDocument.library_id == config.library_id,
        KnowledgeDocument.deleted_at.is_(None),
        Announcement.withdrawn_at.is_(None),
        or_(AnnouncementMeta.effective_at.is_(None), AnnouncementMeta.effective_at <= now),
        or_(AnnouncementMeta.expires_at.is_(None), AnnouncementMeta.expires_at > now),
    )
    # Read acknowledgements must check the current publication after acquiring
    # the library lock, including MySQL REPEATABLE READ transactions.
    return query.with_for_update() if lock else query


def _read_exists(identity):
    return select(1).where(
        AnnouncementRead.user_id == access.user_id(identity),
        AnnouncementRead.document_id == KnowledgeDocument.id,
        AnnouncementRead.revision_id == KnowledgeDocument.published_revision_id,
    ).correlate(KnowledgeDocument).exists()


def _counts(query, identity):
    if query is None:
        return {'total': 0, 'unread_count': 0}
    total, unread = query.with_entities(
        func.count(KnowledgeDocument.id), func.sum(case((~_read_exists(identity), 1), else_=0)),
    ).one()
    return {'total': total, 'unread_count': int(unread or 0)}


def summary(db, identity):
    return _counts(_query(db, identity), identity)


def _serialize(row, *, body=False):
    item, document, revision, meta, is_read = row
    data = {
        'id': document.id, 'revision_id': revision.id, 'title': revision.title,
        'category_name': meta.category_name, 'published_at': item.published_at,
        'pinned': item.pinned, 'important': meta.important, 'is_read': bool(is_read),
    }
    if body:
        data['content_json'] = revision.content_json
    return data


def list_inbox(db, identity, *, unread_only=False, page=1, page_size=20):
    query = _query(db, identity)
    counts = _counts(query, identity)
    if query is None:
        return {'items': [], 'announcement_count': 0, **counts}
    if unread_only:
        query = query.filter(~_read_exists(identity))
    total = query.count()
    rows = query.add_columns(_read_exists(identity).label('is_read')).order_by(
        Announcement.pinned.desc(), Announcement.published_at.desc(), KnowledgeDocument.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [_serialize(row) for row in rows], 'total': total,
            'announcement_count': counts['total'], 'unread_count': counts['unread_count']}


def _row(db, identity, document_id, *, lock=False):
    query = _query(db, identity, lock=lock)
    row = query.add_columns(_read_exists(identity).label('is_read')).filter(
        KnowledgeDocument.id == document_id,
    ).first() if query is not None else None
    if row is None:
        raise knowledge.NotFoundError('公告不存在或已失效')
    return row


def detail(db, identity, document_id):
    # Fetching body has no side effect; the client acknowledges after rendering it.
    return _serialize(_row(db, identity, document_id), body=True)


def _record(db, identity, rows):
    now = beijing_now()
    table = AnnouncementRead.__table__
    values = [{'user_id': access.user_id(identity), 'document_id': document.id,
               'revision_id': revision.id, 'read_at': now} for _, document, revision, _ in rows]
    # Preserve the first read timestamp, including simultaneous/repeated requests.
    for offset in range(0, len(values), 500):
        batch = values[offset:offset + 500]
        if db.get_bind().dialect.name == 'sqlite':
            statement = sqlite_insert(table).values(batch).on_conflict_do_nothing()
        else:
            statement = mysql_insert(table).values(batch).on_duplicate_key_update(read_at=table.c.read_at)
        db.execute(statement)


def _commit(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning('announcement read transaction failed', exc_info=True)
        print('announcement read transaction failed', flush=True)
        raise


def mark_read(db, identity, document_id, revision_id):
    row = _row(db, identity, document_id, lock=True)
    if row[2].id != revision_id:
        raise knowledge.ConflictError('公告已更新，请重新打开后查看')
    _record(db, identity, [row[:4]])
    _commit(db)
    return {'id': document_id, 'revision_id': revision_id, 'is_read': True, **summary(db, identity)}


def mark_all_read(db, identity):
    query = _query(db, identity, lock=True)
    if query is not None:
        _record(db, identity, query.filter(~_read_exists(identity)).all())
        _commit(db)
    return summary(db, identity)
