"""Per-user published-revision reads, exclusively in isolated SQLite."""
from datetime import datetime, timezone

import pytest

from tests.test_announcement import db, ADMIN, EDITOR, READER, identity, doc_json, setup, published
from app.announcement import inbox_service as inbox, service
from app.knowledge import service as knowledge
from app.knowledge.models import KnowledgeDocument
from app.announcement.models import AnnouncementRead, AnnouncementMeta
from app.core.time import to_beijing_naive


def test_inbox_http_contract_and_permission_gate(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.announcement.router import router
    _, row = published(db)
    app = FastAPI()
    app.include_router(router, prefix='/api/announcements')
    app.dependency_overrides[get_db] = lambda: db
    user = dict(READER)
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        assert client.get('/api/announcements/inbox/summary').json()['data']['unread_count'] == 1
        listed = client.get('/api/announcements/inbox', params={'page_size': 1})
        assert listed.status_code == 200 and listed.json()['code'] == 200
        detail = client.get(f'/api/announcements/inbox/{row.document_id}').json()['data']
        result = client.post(f'/api/announcements/inbox/{row.document_id}/read', json={'revision_id': detail['revision_id']})
        assert result.status_code == 200 and result.json()['data']['unread_count'] == 0
        assert client.post('/api/announcements/inbox/read-all').json()['data']['unread_count'] == 0
        assert client.post(f'/api/announcements/inbox/{row.document_id}/read', json={'revision_id': 0}).status_code == 422
        user['permissions'] = []
        assert client.get('/api/announcements/inbox/summary').status_code == 403
        assert client.post('/api/announcements/inbox/read-all').status_code == 403


def test_read_migration_resumes_and_preserves_facts():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateTable
    path = Path(__file__).parents[1] / 'alembic/versions/182_announcement_reads.py'
    spec = importlib.util.spec_from_file_location('read_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.exec_driver_sql('INSERT INTO ark_announcement_reads VALUES (1, 2, 3, "2026-10-10 00:01:00")')
        migration.upgrade()
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM ark_announcement_reads').scalar() == 1
        assert inspect(connection).get_pk_constraint('ark_announcement_reads')['constrained_columns'] == ['user_id', 'document_id', 'revision_id']
        with pytest.raises(RuntimeError, match='preserved'):
            migration.downgrade()
    assert len(migration.revision) <= 32
    sql = str(CreateTable(AnnouncementRead.__table__).compile(dialect=mysql.dialect()))
    assert 'PRIMARY KEY (user_id, document_id, revision_id)' in sql
    assert 'FOREIGN KEY(user_id) REFERENCES ark_users (id)' in sql
    assert 'user_id INTEGER UNSIGNED NOT NULL' in sql
    # Exercise the migration's columns, not only the separately declared ORM model.
    captured = []
    fresh_engine = create_engine('sqlite://')
    class CaptureOperations:
        def get_bind(self):
            return fresh_engine
        def create_table(self, name, *columns):
            captured.extend(columns)
    migration.op = CaptureOperations()
    migration.upgrade()
    assert str(captured[0].type.compile(dialect=mysql.dialect())) == 'INTEGER UNSIGNED'
    fresh_engine.dispose()
    engine.dispose()


def test_uninitialized_and_empty_library_are_empty(db):
    assert inbox.summary(db, READER) == {'total': 0, 'unread_count': 0}
    assert inbox.list_inbox(db, READER)['items'] == []
    setup(db)
    assert inbox.summary(db, READER) == {'total': 0, 'unread_count': 0}
    assert inbox.mark_all_read(db, READER)['unread_count'] == 0


def test_detail_does_not_mark_read_and_mark_is_idempotent_and_user_scoped(db):
    _, row = published(db)
    data = inbox.detail(db, READER, row.document_id)
    assert data['is_read'] is False and data['content_json']
    assert inbox.summary(db, READER)['unread_count'] == 1
    result = inbox.mark_read(db, READER, row.document_id, data['revision_id'])
    assert result['unread_count'] == 0 and result['is_read'] is True
    assert inbox.detail(db, READER, row.document_id)['is_read'] is True
    first_read_at = db.query(AnnouncementRead).one().read_at
    inbox.mark_read(db, READER, row.document_id, data['revision_id'])
    assert db.query(AnnouncementRead).count() == 1
    assert db.query(AnnouncementRead).one().read_at == first_read_at
    assert inbox.summary(db, ADMIN)['unread_count'] == 1


def test_drafts_never_enter_inbox_even_for_managers_and_updates_remind_again(db):
    _, row = published(db)
    data = inbox.detail(db, READER, row.document_id)
    inbox.mark_read(db, READER, row.document_id, data['revision_id'])
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    service.save_announcement(db, EDITOR, document_id=row.document_id, base_revision_id=current['revision_id'],
        title='Secret draft', content=doc_json('Unapproved content'), category_id=current['category_id'])
    assert inbox.list_inbox(db, ADMIN)['items'][0]['title'] == 'Notice'
    assert inbox.detail(db, ADMIN, row.document_id)['title'] == 'Notice'
    assert inbox.summary(db, READER)['unread_count'] == 0
    service.submit(db, EDITOR, row.document_id)
    service.review(db, ADMIN, row.document_id, approve=True)
    assert inbox.summary(db, READER)['unread_count'] == 1
    with pytest.raises(knowledge.ConflictError):
        inbox.mark_read(db, READER, row.document_id, data['revision_id'])
    assert inbox.summary(db, READER)['unread_count'] == 1
    assert db.query(AnnouncementRead).count() == 1


def test_visibility_and_library_acl_apply_to_every_operation(db):
    _, row = published(db)
    data = inbox.detail(db, READER, row.document_id)
    outsider = identity(4, ['announcement:read'])
    with pytest.raises(knowledge.NotFoundError):
        inbox.summary(db, outsider)
    with pytest.raises(knowledge.NotFoundError):
        inbox.mark_all_read(db, outsider)
    with pytest.raises(knowledge.ForbiddenError):
        inbox.summary(db, identity(3, []))
    service.withdraw(db, ADMIN, row.document_id, 'Cancelled')
    assert inbox.summary(db, READER) == {'total': 0, 'unread_count': 0}
    with pytest.raises(knowledge.NotFoundError):
        inbox.detail(db, ADMIN, row.document_id)
    with pytest.raises(knowledge.NotFoundError):
        inbox.mark_read(db, READER, row.document_id, data['revision_id'])
    assert db.query(AnnouncementRead).count() == 0


def test_filters_and_pagination_count_all_visible_rows(db):
    _, category = setup(db)
    ids = []
    for title in ('First', 'Second', 'Third'):
        row = service.save_announcement(db, EDITOR, title=title, content=doc_json(title), category_id=category.id)
        service.submit(db, EDITOR, row.document_id)
        service.review(db, ADMIN, row.document_id, approve=True)
        ids.append(row.document_id)
    first = inbox.detail(db, READER, ids[0])
    inbox.mark_read(db, READER, ids[0], first['revision_id'])
    page = inbox.list_inbox(db, READER, unread_only=True, page_size=1)
    assert page['total'] == 2 and page['unread_count'] == 2 and page['announcement_count'] == 3
    assert len(page['items']) == 1 and not page['items'][0]['is_read']
    result = inbox.mark_all_read(db, READER)
    assert result == {'total': 3, 'unread_count': 0}
    assert inbox.list_inbox(db, READER, unread_only=True)['items'] == []
    assert db.query(AnnouncementRead).count() == 3
    assert inbox.summary(db, ADMIN)['unread_count'] == 3


@pytest.mark.parametrize('instant,expected', [
    (datetime(2026, 10, 9, 15, 59, tzinfo=timezone.utc), datetime(2026, 10, 9, 23, 59)),
    (datetime(2026, 10, 9, 16, 1, tzinfo=timezone.utc), datetime(2026, 10, 10, 0, 1)),
])
def test_read_timestamp_is_beijing_and_validity_uses_same_clock(db, monkeypatch, instant, expected):
    _, row = published(db)
    data = inbox.detail(db, READER, row.document_id)
    monkeypatch.setattr(inbox, 'beijing_now', lambda: to_beijing_naive(instant))
    meta = db.get(AnnouncementMeta, data['revision_id'])
    meta.effective_at = datetime(2026, 10, 9, 23, 58)
    meta.expires_at = datetime(2026, 10, 10, 0, 2)
    db.commit()
    inbox.mark_read(db, READER, row.document_id, data['revision_id'])
    assert db.query(AnnouncementRead).one().read_at == expected
    meta.expires_at = expected
    db.commit()
    assert inbox.summary(db, READER)['total'] == 0


def test_unpublished_deleted_and_future_notices_are_not_counted(db, monkeypatch):
    _, category = setup(db)
    draft = service.save_announcement(db, EDITOR, title='Draft', content=doc_json('Draft'), category_id=category.id)
    assert inbox.summary(db, ADMIN)['total'] == 0
    service.submit(db, EDITOR, draft.document_id)
    service.review(db, ADMIN, draft.document_id, approve=True)
    revision = inbox.detail(db, READER, draft.document_id)['revision_id']
    monkeypatch.setattr(inbox, 'beijing_now', lambda: datetime(2026, 10, 10, 0, 0))
    db.get(AnnouncementMeta, revision).effective_at = datetime(2026, 10, 11)
    db.commit()
    assert inbox.summary(db, READER)['total'] == 0
    db.get(AnnouncementMeta, revision).effective_at = None
    db.get(KnowledgeDocument, draft.document_id).deleted_at = datetime(2026, 10, 10)
    db.commit()
    assert inbox.mark_all_read(db, READER)['total'] == 0
    assert db.query(AnnouncementRead).count() == 0
