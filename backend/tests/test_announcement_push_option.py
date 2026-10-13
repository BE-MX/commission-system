"""Per-revision push policy uses an isolated database and never sends messages."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
import importlib.util
from pathlib import Path

from tests.test_announcement import db, setup, published, EDITOR, ADMIN, READER, doc_json
from app.announcement import service, weekly
from app.announcement.models import AnnouncementMeta, Delivery, Publication, WeeklyReport
from app.knowledge import service as knowledge
from app.knowledge.models import KnowledgeDocument


def save(db, category_id, *, push, current=None):
    return service.save_announcement(db, EDITOR, title='Notice', content=doc_json('正文'),
        category_id=category_id, push_dingtalk=push,
        document_id=current['id'] if current else None,
        base_revision_id=current['revision_id'] if current else None)


def publish(db, row):
    service.submit(db, EDITOR, row.document_id)
    service.review(db, ADMIN, row.document_id, approve=True)


def test_site_only_publish_and_withdraw_work_without_group(db):
    config, category = setup(db)
    config.delivery_enabled = config.channel_verified = False
    config.conversation_id = config.robot_code = ''
    db.commit()
    row = save(db, category.id, push=False)
    publish(db, row)
    detail = service.detail(db, READER, row.document_id)
    assert detail['status'] == 'published' and detail['push_dingtalk'] is False
    assert db.query(Publication).count() == 1
    assert db.query(Delivery).count() == 0
    event = db.query(Publication).one()
    event.created_at = datetime(2026, 9, 15)
    db.commit()
    assert weekly.collect_sources(db, datetime(2026, 9, 14), datetime(2026, 9, 21)) == []
    service.withdraw(db, ADMIN, row.document_id, '撤回')
    assert db.query(Delivery).count() == 0
    assert service.detail(db, READER, row.document_id)['status'] == 'withdrawn'


def test_push_requires_channel_at_submit_and_approval(db):
    config, category = setup(db)
    row = save(db, category.id, push=True)
    config.delivery_enabled = False
    db.commit()
    with pytest.raises(knowledge.ConflictError, match='图文通道'):
        service.submit(db, EDITOR, row.document_id)
    db.rollback()
    assert db.get(KnowledgeDocument, row.document_id).pending_approval_id is None
    config.delivery_enabled = True
    db.commit()
    service.submit(db, EDITOR, row.document_id)
    config.delivery_enabled = False
    db.commit()
    with pytest.raises(knowledge.ConflictError, match='图文通道'):
        service.review(db, ADMIN, row.document_id, approve=True)
    db.rollback()
    assert db.get(KnowledgeDocument, row.document_id).published_revision_id is None
    assert db.query(Publication).count() == db.query(Delivery).count() == 0
    config.delivery_enabled = True
    db.commit()
    service.review(db, ADMIN, row.document_id, approve=True)
    assert db.query(Delivery).count() > 0


@pytest.mark.parametrize('old_status', ['queued', 'sent', 'uncertain', 'sending'])
def test_site_only_update_cancels_old_queue_and_keeps_prior_corrections(db, old_status):
    config, row = published(db)
    old_task = db.query(Delivery).first()
    old_task.status = old_status
    old_event = db.query(Publication).one()
    old_event.created_at = datetime(2026, 9, 15)
    db.commit()
    source = {'document_id': row.document_id, 'revision_id': old_event.revision_id, 'kind': 'publish'}
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    save(db, current['category_id'], push=False, current=current)
    # Published policy stays on the old version until approval.
    assert service.detail(db, READER, row.document_id)['push_dingtalk'] is True
    config.delivery_enabled = False
    db.commit()
    publish(db, row)
    assert service.detail(db, READER, row.document_id)['push_dingtalk'] is False
    new_event = db.query(Publication).filter_by(kind='update').one()
    assert db.query(Delivery).filter_by(publication_id=new_event.id).count() == 0
    assert old_task.status == ('cancelled' if old_status == 'queued' else old_status)
    assert weekly.sources_valid(db, [source]) is False
    assert weekly.collect_sources(db, datetime(2026, 9, 14), datetime(2026, 9, 21)) == []
    service.withdraw(db, ADMIN, row.document_id, '撤回')
    withdrawal = db.query(Publication).filter_by(kind='withdraw').one()
    assert bool(db.query(Delivery).filter_by(publication_id=withdrawal.id).count()) == (old_status != 'queued')


def test_push_choice_is_frozen_during_review_and_can_change_on_new_revision(db):
    _, category = setup(db)
    row = save(db, category.id, push=False)
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    service.submit(db, EDITOR, row.document_id)
    with pytest.raises(knowledge.ConflictError, match='待审核'):
        save(db, category.id, push=True, current=current)
    db.rollback()
    assert db.get(AnnouncementMeta, current['revision_id']).push_dingtalk is False
    service.review(db, ADMIN, row.document_id, approve=True)
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    save(db, category.id, push=True, current=current)
    publish(db, row)
    assert db.query(Delivery).count() > 0
    assert db.get(AnnouncementMeta, current['revision_id']).push_dingtalk is False


def test_site_only_notices_do_not_lock_group_configuration(db):
    from app.announcement.settings_service import get_config, update_config
    _, category = setup(db)
    row = save(db, category.id, push=False)
    publish(db, row)
    data = {k: v for k, v in get_config(db, ADMIN).items() if k not in {'initialized', 'library_id', 'channel_verified'}}
    data.update(conversation_id='new-group', delivery_enabled=False)
    assert update_config(db, ADMIN, data)['conversation_id'] == 'new-group'


@pytest.mark.parametrize('historical_generation', [False, True])
def test_weekly_exposure_locks_original_group_and_requires_withdrawal_correction(db, historical_generation):
    from app.announcement.settings_service import get_config, update_config
    config, row = published(db)
    db.query(Delivery).update({'status': 'cancelled'})
    event = db.query(Publication).one()
    event.created_at = datetime(2026, 9, 15)
    db.commit()
    report = weekly.request_report(db, ADMIN, now=datetime(2026, 9, 21))
    report.status, report.body = 'ready', 'Weekly notice'
    weekly.enqueue_report(db, config, report)
    db.query(Delivery).filter_by(weekly_id=report.id).update({'status': 'sent'})
    if historical_generation:
        report.history = [{'generation': 1, 'sources': report.sources}]
        report.generation, report.sources = 2, []
    db.commit()
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    save(db, current['category_id'], push=False, current=current)
    publish(db, row)
    data = {k: v for k, v in get_config(db, ADMIN).items() if k not in {'initialized', 'library_id', 'channel_verified'}}
    data.update(conversation_id='new-group', delivery_enabled=False)
    with pytest.raises(knowledge.ConflictError, match='原群'):
        update_config(db, ADMIN, data)
    db.rollback()
    service.withdraw(db, ADMIN, row.document_id, '更正旧周报')
    withdrawal = db.query(Publication).filter_by(kind='withdraw').one()
    tasks = db.query(Delivery).filter_by(publication_id=withdrawal.id).all()
    assert tasks and all(task.target == 'test-conversation' for task in tasks)


def test_http_push_false_survives_save_and_review_without_channel(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.announcement.router import router
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    app = FastAPI()
    app.include_router(router, prefix='/api/announcements')
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        client.post('/api/announcements/initialize')
        category = client.post('/api/announcements/categories', json={'title': '公司通知'}).json()['data']
        response = client.post('/api/announcements', json={'title': 'Site only', 'category_id': category['id'],
            'content': doc_json('正文'), 'push_dingtalk': False})
        assert response.status_code == 200
        doc_id = response.json()['data']['id']
        detail = client.get(f'/api/announcements/{doc_id}', params={'edit': True}).json()['data']
        assert detail['push_dingtalk'] is False
        assert client.post(f'/api/announcements/{doc_id}/submit').status_code == 200
        assert client.post(f'/api/announcements/{doc_id}/review', json={'approve': True}).status_code == 200
        assert client.get('/api/announcements').json()['data']['items'][0]['push_dingtalk'] is False
        assert db.query(Delivery).count() == 0


def test_migration_preserves_old_true_and_new_false_on_repeat():
    path = Path(__file__).parents[1] / 'alembic/versions/185_announcement_push_option.py'
    spec = importlib.util.spec_from_file_location('push_option_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE ark_announcement_revision_meta (revision_id BIGINT PRIMARY KEY)')
        connection.exec_driver_sql('INSERT INTO ark_announcement_revision_meta VALUES (1)')
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.exec_driver_sql('SELECT push_dingtalk FROM ark_announcement_revision_meta').scalar() == 1
        connection.exec_driver_sql('INSERT INTO ark_announcement_revision_meta VALUES (2, 0)')
        migration.upgrade()
        assert connection.exec_driver_sql('SELECT push_dingtalk FROM ark_announcement_revision_meta WHERE revision_id=2').scalar() == 0
        assert inspect(connection).get_columns('ark_announcement_revision_meta')[1]['nullable'] is False
        assert len(migration.revision) <= 32
        with pytest.raises(RuntimeError, match='preserved'):
            migration.downgrade()
    engine.dispose()


def test_mysql_push_column_compiles_with_historical_true_default():
    from sqlalchemy import Column, Boolean
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateColumn
    from sqlalchemy.sql import true
    ddl = str(CreateColumn(Column('push_dingtalk', Boolean(), nullable=False, server_default=true())).compile(dialect=mysql.dialect()))
    assert 'NOT NULL' in ddl and 'DEFAULT true' in ddl
