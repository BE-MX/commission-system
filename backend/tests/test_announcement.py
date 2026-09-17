"""Announcement contracts tested exclusively against an in-memory database."""
from datetime import datetime, timezone

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base
from app.auth.models import ArkUser, ArkRole, ArkPermission
from app.announcement import service, rendering, weekly
from app.announcement.models import AnnouncementConfig, Announcement, AnnouncementMeta, Publication, Delivery, WeeklyReport
from app.knowledge import service as knowledge
from app.knowledge.models import KnowledgeLibrary, KnowledgeLibraryMember, KnowledgeDocument

def identity(uid, permissions):
    return {'sub': str(uid), 'permissions': permissions, 'roles': []}


def doc_json(text):
    return {'type': 'doc', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}]}


@pytest.fixture()
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    prefixes = ('ark_knowledge_', 'ark_announcement_', 'ark_ai_')
    names = {'ark_users', 'ark_roles', 'ark_permissions', 'ark_user_roles', 'ark_role_permissions'}
    tables = [t for t in Base.metadata.sorted_tables if t.name.startswith(prefixes) or t.name in names]
    Base.metadata.create_all(engine, tables=tables)
    with sessionmaker(bind=engine)() as session:
        session.add_all([ArkUser(id=i, username=f'user{i}', real_name=f'User {i}', password_hash='test', is_active=True) for i in range(1, 5)])
        for uid, code in [(1, 'announcement:admin'), (2, 'announcement:write'), (3, 'announcement:read')]:
            role = ArkRole(name=f'test-role-{uid}', label='Test', permissions=[ArkPermission(code=code, module='announcement', action=code.split(':')[1], label='Test')])
            user = session.get(ArkUser, uid)
            user.roles.append(role)
        session.commit()
        yield session
    engine.dispose()
ADMIN = identity(1, ['announcement:admin', 'knowledge:review'])
EDITOR = identity(2, ['announcement:write'])
READER = identity(3, ['announcement:read'])


def setup(db):
    config = service.initialize(db, ADMIN)
    db.add_all([KnowledgeLibraryMember(library_id=config.library_id, user_id=uid, role=role, created_by=1)
                for uid, role in [(2, 'editor'), (3, 'viewer')]])
    config.group_name = 'Test group'
    config.conversation_id = 'test-conversation'
    config.robot_code = 'test-robot'
    config.delivery_enabled = True
    config.channel_verified = True
    db.commit()
    category = service.save_category(db, ADMIN, title='公司通知')
    return config, category


def draft(db):
    config, category = setup(db)
    row = service.save_announcement(db, EDITOR, title='Notice', content=doc_json('请于周五完成登记'), category_id=category.id)
    return config, row


def test_draft_acl_and_managed_library_guard(db):
    config, row = draft(db)
    assert service.list_announcements(db, READER)['total'] == 0
    with pytest.raises(knowledge.NotFoundError):
        service.detail(db, READER, row.document_id)
    with pytest.raises(knowledge.ConflictError):
        knowledge.save_document(db, identity(2, ['knowledge:write']), row.document_id, title='bypass', content=doc_json('bad'))
    assert db.query(KnowledgeLibrary).count() == 1
    assert db.query(KnowledgeDocument).filter_by(node_type='document').count() == 1


def test_publish_outbox_and_update_preserves_reader_version(db):
    config, row = draft(db)
    service.submit(db, EDITOR, row.document_id)
    service.review(db, ADMIN, row.document_id, approve=True)
    assert db.query(Publication).count() == 1
    assert db.query(Delivery).count() >= 1
    assert service.detail(db, READER, row.document_id)['title'] == 'Notice'
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    service.save_announcement(db, EDITOR, document_id=row.document_id, base_revision_id=current['revision_id'],
                              title='Updated', category_id=current['category_id'], content=doc_json('新内容'))
    assert service.detail(db, READER, row.document_id)['title'] == 'Notice'
    with pytest.raises(knowledge.ConflictError):
        service.review(db, ADMIN, row.document_id, approve=True)


def test_rendering_keeps_long_text_and_images_in_order():
    content = doc_json('中文' * 3000)
    content['content'].append({'type': 'knowledgeImage', 'attrs': {'assetId': 42, 'alt': '图示'}})
    content['content'] += doc_json('结束')['content']
    parts = rendering.render_parts(content)
    assert ''.join(p['text'] for p in parts if p['kind'] == 'text').count('中文') == 3000
    assert next(p for p in parts if p['kind'] == 'image')['asset_id'] == 42
    assert parts[-1]['text'].endswith('结束')


def test_week_boundaries_use_beijing():
    start, end = weekly.period_for(datetime(2026, 9, 20, 17, 0, tzinfo=timezone.utc))
    assert start == datetime(2026, 9, 14)
    assert end == datetime(2026, 9, 21)


def published(db):
    config, row = draft(db)
    service.submit(db, EDITOR, row.document_id)
    service.review(db, ADMIN, row.document_id, approve=True)
    return config, row


def test_viewer_tree_never_discloses_unapproved_title(db):
    config, row = published(db)
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    service.save_announcement(db, EDITOR, document_id=row.document_id, base_revision_id=current['revision_id'],
        title='SECRET DRAFT TITLE', category_id=current['category_id'], content=doc_json('unapproved'))
    tree = knowledge.get_tree(db, identity(3, ['knowledge:read']), config.library_id)
    assert next(n for n in tree if n['id'] == row.document_id)['title'] == 'Notice'


def test_publish_transaction_does_not_commit_before_outbox(db, monkeypatch):
    _, row = draft(db)
    service.submit(db, EDITOR, row.document_id)
    def fail(*args, **kwargs):
        raise RuntimeError('outbox failure')
    monkeypatch.setattr(service, 'enqueue', fail)
    with pytest.raises(RuntimeError):
        service.review(db, ADMIN, row.document_id, approve=True)
    db.rollback()
    assert db.get(KnowledgeDocument, row.document_id).published_revision_id is None
    assert db.query(Publication).count() == db.query(Delivery).count() == 0


def test_withdraw_clears_search_and_cancels_remaining_parts(db):
    config, row = published(db)
    service.withdraw(db, ADMIN, row.document_id, '发布错误')
    assert knowledge.search_published(db, identity(3, ['knowledge:read']), 'Notice') == []
    assert service.detail(db, READER, row.document_id)['status'] == 'withdrawn'
    assert 'content_json' not in service.detail(db, READER, row.document_id)
    assert {t.status for t in db.query(Delivery).filter_by(source_key='publication:1')} == {'cancelled'}


def test_dispatch_and_duplicate_claim(db, monkeypatch):
    from app.announcement import delivery
    published(db)
    sent = []
    monkeypatch.setattr(delivery.transport, 'prepare_message', lambda *_: ('token', 'key', {}))
    monkeypatch.setattr(delivery.transport, 'send_message', lambda *args: sent.append(args) or 'receipt')
    task = delivery.claim(db)
    assert delivery.claim(db) is None  # blocked by earlier preparing part
    delivery.execute(db, *task)
    delivery.execute(db, *task)
    assert len(sent) == 1
    assert db.get(Delivery, task[0]).status == 'sent'
    assert delivery.claim(db) is not None


def test_withdraw_during_image_preparation_prevents_send(db, monkeypatch):
    from app.announcement import delivery
    _, row = published(db)
    sent = []
    def prepare(*_):
        service.withdraw(db, ADMIN, row.document_id, '已取消')
        return ('token', 'key', {})
    monkeypatch.setattr(delivery.transport, 'prepare_message', prepare)
    monkeypatch.setattr(delivery.transport, 'send_message', lambda *args: sent.append(args))
    task = delivery.claim(db)
    delivery.execute(db, *task)
    assert sent == []
    assert db.get(Delivery, task[0]).status == 'cancelled'


def test_lost_lease_cannot_send_or_overwrite_new_owner(db, monkeypatch):
    from app.announcement import delivery
    published(db)
    task = delivery.claim(db)
    def prepare(*_):
        row = db.get(Delivery, task[0])
        row.lease_token = 'new-owner'
        db.commit()
        return ('token', 'key', {})
    sent = []
    monkeypatch.setattr(delivery.transport, 'prepare_message', prepare)
    monkeypatch.setattr(delivery.transport, 'send_message', lambda *args: sent.append(args))
    delivery.execute(db, *task)
    assert sent == []
    assert db.get(Delivery, task[0]).lease_token == 'new-owner'


def test_uncertain_delivery_is_not_automatically_retried(db, monkeypatch):
    from app.announcement import delivery
    published(db)
    monkeypatch.setattr(delivery.transport, 'prepare_message', lambda *_: ('token', 'key', {}))
    def timeout(*_):
        raise delivery.transport.AnnouncementSendError('timeout', uncertain=True)
    monkeypatch.setattr(delivery.transport, 'send_message', timeout)
    task = delivery.claim(db)
    delivery.execute(db, *task)
    assert db.get(Delivery, task[0]).status == 'uncertain'
    assert delivery.claim(db) is None
    with pytest.raises(knowledge.ConflictError):
        delivery.retry(db, ADMIN, task[0])
    delivery.retry(db, ADMIN, task[0], confirm_uncertain=True, mark_delivered=True)
    assert delivery.claim(db) is not None


def test_acl_shrink_cancels_queued_payload(db):
    from app.announcement import delivery
    config, _ = published(db)
    db.query(KnowledgeLibraryMember).filter_by(library_id=config.library_id, user_id=3).delete()
    db.commit()
    with pytest.raises(knowledge.ConflictError, match='成员权限'):
        delivery.allowed(db, db.query(Delivery).first())


def test_weekly_sources_include_old_announcement_withdrawal(db):
    _, row = published(db)
    event = db.query(Publication).first()
    event.created_at = datetime(2026, 8, 1)
    db.commit()
    service.withdraw(db, ADMIN, row.document_id, '旧制度撤回')
    withdrawn = db.query(Publication).filter_by(kind='withdraw').one()
    withdrawn.created_at = datetime(2026, 9, 16)
    db.commit()
    sources = weekly.collect_sources(db, datetime(2026, 9, 14), datetime(2026, 9, 21))
    assert len(sources) == 1 and sources[0]['kind'] == 'withdraw'


def test_weekly_idempotency_verbatim_validation_and_fallback(db, monkeypatch):
    _, row = published(db)
    event = db.query(Publication).one()
    start, end = weekly.period_for()
    event.created_at = start
    db.commit()
    report = weekly.request_report(db, ADMIN)
    assert weekly.request_report(db, ADMIN).id == report.id
    monkeypatch.setattr(weekly, 'chat', lambda *a, **kw: {'content': '{"999":["fabricated"]}'})
    weekly.execute_next(db)
    db.refresh(report)
    assert report.status == 'degraded'
    assert 'Notice' in report.body and 'fabricated' not in report.body
    assert db.query(Delivery).filter_by(weekly_id=report.id).count() == 0
    weekly.send_report(db, ADMIN, report.id)
    with pytest.raises(knowledge.ConflictError):
        weekly.send_report(db, ADMIN, report.id)


def test_weekly_ai_output_must_cover_each_source_without_invention():
    source = [{'event_id': 1, 'text': '请周五完成登记。'}]
    assert weekly.validate_selections('{"1":["请周五完成登记。"]}', source)
    with pytest.raises(ValueError):
        weekly.validate_selections('{"1":["请周六完成登记。"]}', source)


def test_saving_foreign_library_or_stale_revision_is_rejected(db):
    config, row = draft(db)
    other = knowledge.create_library(db, identity(1, ['knowledge:admin']), name='Private', category='personal')
    other_folder = knowledge.create_folder(db, identity(1, ['knowledge:admin']), other.id, title='Secret')
    with pytest.raises(knowledge.NotFoundError):
        service.save_announcement(db, EDITOR, title='bad', content=doc_json('bad'), category_id=other_folder.id)
    db.rollback()
    current = service.detail(db, EDITOR, row.document_id, edit=True)
    with pytest.raises(knowledge.ConflictError):
        service.save_announcement(db, EDITOR, document_id=row.document_id, base_revision_id=999,
            title='bad', content=doc_json('bad'), category_id=current['category_id'])


def test_http_announcement_round_trip_and_reader_write_rejection(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.announcement.router import router
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    app = FastAPI()
    app.include_router(router, prefix='/api/announcements')
    current = dict(ADMIN)
    app.dependency_overrides[get_current_user] = lambda: current
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get('/api/announcements/config').json()['data'] == {'initialized': False}
        assert client.post('/api/announcements/initialize').status_code == 200
        category = client.post('/api/announcements/categories', json={'title': '公司通知'}).json()['data']
        response = client.post('/api/announcements', json={'title': 'API notice', 'category_id': category['id'], 'content': doc_json('正文')})
        assert response.status_code == 200, response.text
        doc_id = response.json()['data']['id']
        detail = client.get(f'/api/announcements/{doc_id}', params={'edit': True}).json()['data']
        assert detail['content_json'] == doc_json('正文')
        assert client.get(f'/api/announcements/{doc_id}/preview').status_code == 200
        current.clear(); current.update(READER)
        assert client.post('/api/announcements', json={'title': 'bad', 'category_id': category['id'], 'content': doc_json('bad')}).status_code == 403
        assert client.get(f'/api/announcements/{doc_id}').status_code == 404
        assert client.post(f'/api/announcements/{doc_id}/review', json={'approve': True}).status_code == 403


def test_group_cannot_change_while_published_notices_need_corrections(db):
    from app.announcement.settings_service import get_config, update_config
    published(db)
    data = get_config(db, ADMIN)
    data = {k: v for k, v in data.items() if k not in {'initialized', 'library_id', 'channel_verified'}}
    data['conversation_id'] = 'different-group'
    with pytest.raises(knowledge.ConflictError, match='原群'):
        update_config(db, ADMIN, data)


def test_empty_body_cannot_be_submitted(db):
    _, category = setup(db)
    row = service.save_announcement(db, EDITOR, title='Empty', content=doc_json(''), category_id=category.id)
    with pytest.raises(knowledge.ValidationError, match='正文'):
        service.submit(db, EDITOR, row.document_id)


def test_expired_sending_recovers_uncertain_and_old_result_cannot_override(db, monkeypatch):
    from datetime import timedelta
    from app.announcement import delivery
    from app.core.time import beijing_now
    published(db)
    task = delivery.claim(db)
    monkeypatch.setattr(delivery.transport, 'prepare_message', lambda *_: ('token', 'key', {}))
    def late_result(*_):
        row = db.get(Delivery, task[0])
        row.lease_until = beijing_now() - timedelta(seconds=1)
        db.commit()
        delivery.recover(db)
        return 'late-receipt'
    monkeypatch.setattr(delivery.transport, 'send_message', late_result)
    delivery.execute(db, *task)
    assert db.get(Delivery, task[0]).status == 'uncertain'


def test_dates_normalize_offset_and_cross_beijing_midnight(db):
    _, category = setup(db)
    row = service.save_announcement(db, EDITOR, title='Times', content=doc_json('正文'), category_id=category.id,
        effective_at=datetime(2026, 9, 17, 16, tzinfo=timezone.utc), expires_at=datetime(2026, 9, 18, 0, tzinfo=timezone.utc))
    result = service.detail(db, EDITOR, row.document_id, edit=True)
    assert result['effective_at'] == datetime(2026, 9, 18)
    assert result['expires_at'] == datetime(2026, 9, 18, 8)


def test_ai_weekly_uses_verbatim_sources_and_automatic_outbox(db, monkeypatch):
    config, _ = published(db)
    start, _ = weekly.period_for()
    event = db.query(Publication).one()
    event.created_at = start
    db.commit()
    report = weekly.request_report(db, ADMIN, auto_send=True)
    monkeypatch.setattr(weekly, 'chat', lambda *a, **kw: {'content': '{"1":["请于周五完成登记"]}'})
    weekly.execute_next(db)
    db.refresh(report)
    assert report.status == 'ready'
    assert '请于周五完成登记' in report.body
    assert db.query(Delivery).filter_by(weekly_id=report.id).count() > 0


@pytest.mark.parametrize('resolve', ['delivered', 'cancel'])
def test_uncertain_history_can_be_resolved_after_withdrawal(db, resolve):
    from app.announcement import delivery
    _, item = published(db)
    task = db.query(Delivery).first()
    task.status = 'uncertain'
    db.commit()
    service.withdraw(db, ADMIN, item.document_id, '撤回原因')
    delivery.retry(db, ADMIN, task.id, confirm_uncertain=True,
                   mark_delivered=resolve == 'delivered', cancel=resolve == 'cancel')
    assert task.status == ('sent' if resolve == 'delivered' else 'cancelled')


def test_weekly_expired_lease_cannot_store_body_or_enqueue(db, monkeypatch):
    from datetime import timedelta
    from app.core.time import beijing_now
    published(db)
    start, _ = weekly.period_for()
    db.query(Publication).one().created_at = start
    db.commit()
    report = weekly.request_report(db, ADMIN, auto_send=True)
    def expired(*args, **kwargs):
        db.get(WeeklyReport, report.id).lease_until = beijing_now() - timedelta(seconds=1)
        db.commit()
        return {'content': '{"1":["请于周五完成登记"]}'}
    monkeypatch.setattr(weekly, 'chat', expired)
    weekly.execute_next(db)
    assert db.get(WeeklyReport, report.id).status == 'generating'
    assert db.query(Delivery).filter_by(weekly_id=report.id).count() == 0


def test_scheduler_uses_injected_beijing_week_boundary(db):
    config, _ = setup(db)
    config.weekly_enabled = True
    db.commit()
    weekly.schedule_due(db, datetime(2026, 9, 21, 0, 59, tzinfo=timezone.utc))
    assert db.query(WeeklyReport).count() == 0
    weekly.schedule_due(db, datetime(2026, 9, 21, 1, tzinfo=timezone.utc))
    report = db.query(WeeklyReport).one()
    assert report.period_start == datetime(2026, 9, 14)
    assert report.period_end == datetime(2026, 9, 21)


def test_blocked_parts_do_not_starve_independent_deliveries(db):
    from app.announcement import delivery
    config, _ = setup(db)
    for index in range(105):
        db.add(Delivery(source_key='blocked', sequence=index + 1, target='group', robot_code='robot',
            config_version=config.version, payload={}, status='failed' if index == 0 else 'queued'))
    next_task = Delivery(source_key='independent', sequence=1, target='group', robot_code='robot',
        config_version=config.version, payload={}, status='queued')
    db.add(next_task)
    db.commit()
    assert delivery.claim(db)[0] == next_task.id
