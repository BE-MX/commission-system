"""Recovery, version authority, role limits and accounting on isolated SQLite."""
from datetime import timedelta

import pytest

from app.ai_chat import service, workspace_service as workspace
from app.ai_chat import generation_service as generation, management_service as management
from app.ai_chat.models import AiChatMessage
from app.ai_chat.schemas import RetryStreamRequest
from app.auth.models import ArkRole, ArkUserRole
from app.core.time import beijing_now
from tests.test_universal_ai_chat import owner, model, request  # noqa: F401


def turn(db, owner):
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    pair = workspace.begin_turn(db, owner.id, session.id, request(preset.id))
    return preset, session, pair


def test_expired_generation_recovers_partial_content_and_fences_late_worker(db, owner):
    _, session, pair = turn(db, owner)
    generation.checkpoint(db, owner.id, pair.assistant_message.id, 'partial', 'thinking')
    row = pair.assistant_message
    db.refresh(row)
    row.lease_expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    assert generation.recover_expired(db, owner.id) == 1
    with pytest.raises(generation.GenerationLost):
        generation.checkpoint(db, owner.id, row.id, 'late', '')
    service.finish_turn(db, owner.id, row.id, 'late complete')
    db.refresh(row)
    assert (row.status, row.content, row.finish_reason) == ('failed', 'partial', 'lease_expired')
    assert row.reasoning_content == 'thinking'
    workspace.delete_session(db, owner.id, session.id)


def test_live_lease_survives_recovery_and_legacy_stale_rows_can_recover(db, owner):
    _, _, pair = turn(db, owner)
    assert generation.recover_expired(db, owner.id) == 0
    row = pair.assistant_message
    row.lease_expires_at = None
    row.updated_at = beijing_now() - timedelta(minutes=10)
    db.commit()
    assert generation.recover_expired(db, owner.id) == 1


def test_continuation_creates_a_version_and_preserves_original(db, owner):
    preset, session, pair = turn(db, owner)
    source = pair.assistant_message
    service.finish_turn(db, owner.id, source.id, 'First half.', finish_reason='length')
    body = RetryStreamRequest(request_id='continue_first', preset_id=preset.id)
    continued = workspace.begin_continuation(db, owner.id, source.id, body)
    assert continued.assistant_message.content == 'First half.'
    assert continued.assistant_message.continuation_of_message_id == source.id
    replay = workspace.begin_continuation(db, owner.id, source.id, body)
    assert replay.reused
    service.finish_turn(db, owner.id, continued.assistant_message.id, 'First half. Second half.', finish_reason='stop')
    db.refresh(source)
    assert source.content == 'First half.'
    assert [m['content'] for m in service.build_context(db, owner.id, session.id)] == ['hello', 'First half. Second half.']
    workspace.select_answer(db, owner.id, pair.user_message.id, source.id)
    assert [m['content'] for m in service.build_context(db, owner.id, session.id)] == ['hello', 'First half.']
    workspace.begin_turn(db, owner.id, session.id, request(preset.id, 'following_turn'))
    with pytest.raises(service.RequestConflictError):
        workspace.select_answer(db, owner.id, pair.user_message.id, continued.assistant_message.id)


def test_multiple_roles_use_strictest_configured_limit_and_deletion_keeps_usage(db, owner):
    preset, session, pair = turn(db, owner)
    service.finish_turn(db, owner.id, pair.assistant_message.id, 'answer')
    roles = [ArkRole(name='limited', label='Limited'), ArkRole(name='generous', label='Generous')]
    db.add_all(roles)
    db.flush()
    db.add_all([ArkUserRole(user_id=owner.id, role_id=r.id) for r in roles])
    db.commit()
    management.set_role_limit(db, roles[0].id, 1, owner.id)
    management.set_role_limit(db, roles[1].id, 20, owner.id)
    assert workspace.usage(db, owner.id)['limit'] == 1
    workspace.delete_session(db, owner.id, session.id)
    new_session = service.create_session(db, owner.id)
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.begin_turn(db, owner.id, new_session.id, request(preset.id, 'over_limit'))
    assert error.value.status_code == 429


def test_recovery_before_admission_with_autoflush_disabled(db, owner):
    preset, session, pair = turn(db, owner)
    pair.assistant_message.lease_expires_at = beijing_now() - timedelta(seconds=2)
    db.commit()
    db.autoflush = False
    fresh = workspace.begin_turn(db, owner.id, session.id, request(preset.id, 'after_expiry'))
    db.refresh(pair.assistant_message)
    assert pair.assistant_message.status == 'failed'
    assert fresh.assistant_message.status == 'streaming'


def test_stale_token_cannot_generate_after_current_permission_revoked(db, owner):
    from app.auth.models import ArkRolePermission
    preset, session, pair = turn(db, owner)
    service.finish_turn(db, owner.id, pair.assistant_message.id, 'prior')
    db.query(ArkRolePermission).delete()
    db.commit()
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.begin_turn(db, owner.id, session.id, request(preset.id, 'revoked_permission'))
    assert error.value.status_code == 403


def test_continuation_does_not_replace_original_idempotency_pair(db, owner):
    preset, session, pair = turn(db, owner)
    service.finish_turn(db, owner.id, pair.assistant_message.id, 'short', finish_reason='length')
    workspace.begin_continuation(db, owner.id, pair.assistant_message.id, RetryStreamRequest(request_id='continued_again'))
    replay = workspace.begin_turn(db, owner.id, session.id, request(preset.id))
    assert replay.reused and replay.assistant_message.id == pair.assistant_message.id


def test_usage_keeps_currencies_and_partial_tokens_distinct(db, owner):
    from app.ai.models import AiCallLog
    preset, session, pair = turn(db, owner)
    first = pair.assistant_message
    first.model_snapshot = {**first.model_snapshot, 'pricing': {'currency': 'USD', 'input_per_million': '2', 'output_per_million': '8'}}
    log = AiCallLog(caller_module='ai_chat', preset_name='test', provider_type='direct', status='success', tokens_prompt=1000, tokens_completion=100, duration_ms=100)
    db.add(log)
    db.commit()
    service.finish_turn(db, owner.id, first.id, 'priced', log.id)
    retry = workspace.begin_retry(db, owner.id, first.id, RetryStreamRequest(request_id='unknown_usage'))
    log2 = AiCallLog(caller_module='ai_chat', preset_name='test', provider_type='direct', status='error', tokens_prompt=45)
    db.add(log2)
    db.commit()
    service.stop_turn(db, owner.id, retry.assistant_message.id, '', log2.id)
    workspace.delete_session(db, owner.id, session.id)
    result = management.usage_report(db)
    assert result['totals']['requests'] == 2
    assert result['totals']['input_tokens'] == 1045
    assert result['totals']['token_requests'] == 1
    assert result['totals']['unpriced_requests'] == 1
    assert result['totals']['estimated_costs'] == {'USD': '0.002800'}
    assert 'content' not in str(result)


def test_recovery_log_cannot_be_overwritten_by_late_finalizer(db, owner):
    import time
    from app.ai.models import AiCallLog
    from app.ai.stream_service import _finalize_log
    _, _, pair = turn(db, owner)
    log = AiCallLog(caller_module='ai_chat', preset_name='test', provider_type='direct', status='pending')
    db.add(log)
    db.flush()
    pair.assistant_message.ai_call_log_id = log.id
    pair.assistant_message.lease_expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    generation.recover_expired(db, owner.id)
    _finalize_log(db, log, time.time(), 'success', {}, 'late')
    db.refresh(log)
    assert (log.status, log.error_code) == ('error', 'generation_interrupted')


@pytest.mark.parametrize('host_zone', ['UTC', 'America/Los_Angeles'])
def test_lease_and_role_audit_use_beijing_across_midnight(db, owner, monkeypatch, host_zone):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from app.core import time as clock
    instant = datetime(2026, 11, 16, 15, 59, 50, tzinfo=timezone.utc)
    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz or ZoneInfo(host_zone))
    monkeypatch.setattr(clock, 'datetime', HostClock)
    assert generation.lease_deadline() == datetime(2026, 11, 17, 0, 0, 35)
    role = db.query(ArkRole).filter_by(name='chat_writer').one()
    management.set_role_limit(db, role.id, 7, owner.id)
    from app.ai_chat.models import AiChatRoleLimit
    assert db.get(AiChatRoleLimit, role.id).updated_at == datetime(2026, 11, 16, 23, 59, 50)


def test_partial_output_counter_is_not_priced_as_complete_usage(db, owner):
    from app.ai.models import AiCallLog
    _, _, pair = turn(db, owner)
    row = pair.assistant_message
    row.model_snapshot = {**row.model_snapshot, 'pricing': {'currency': 'CNY', 'input_per_million': '2', 'output_per_million': '8'}}
    log = AiCallLog(caller_module='ai_chat', preset_name='test', provider_type='direct', status='error',
        tokens_prompt=83, tokens_completion=1, usage_detail={'complete': False})
    db.add(log)
    db.commit()
    service.stop_turn(db, owner.id, row.id, 'partial', log.id)
    totals = management.usage_report(db)['totals']
    assert totals['input_tokens'] == 83 and totals['output_tokens'] == 1
    assert totals['token_requests'] == 0 and totals['unpriced_requests'] == 1
    assert totals['estimated_costs'] == {}


def test_continue_selection_and_management_http_permissions(engine, db, owner):
    from tests.test_universal_ai_chat import client
    preset, session, pair = turn(db, owner)
    source = pair.assistant_message
    service.finish_turn(db, owner.id, source.id, 'truncated', finish_reason='length')
    reader = client(engine, owner.id, ('ai_chat:read',))
    for path, body in [(f'/messages/{source.id}/continue/stream', {'request_id': 'denied_continue'}),
                       (f'/messages/{pair.user_message.id}/selection', {'answer_id': source.id})]:
        response = reader.post('/api/ai-chat' + path, json=body) if 'stream' in path else reader.patch('/api/ai-chat' + path, json=body)
        assert response.status_code == 403
    assert reader.get('/api/ai-chat/admin/usage').status_code == 403
    assert reader.get('/api/ai-chat/admin/role-limits').status_code == 403
    admin = client(engine, owner.id, ('ai:admin',))
    assert admin.get('/api/ai-chat/admin/usage').status_code == 200
    assert admin.get('/api/ai-chat/admin/usage?start=2026-01-01&end=2026-11-01').status_code == 400
    role_id = db.query(ArkRole.id).filter_by(name='chat_writer').scalar()
    assert admin.put(f'/api/ai-chat/admin/role-limits/{role_id}', json={'daily_limit': True}).status_code == 422
    assert admin.put(f'/api/ai-chat/admin/role-limits/{role_id}', json={'daily_limit': 0}).status_code == 200
    assert workspace.usage(db, owner.id)['remaining'] == 0


def test_generation_first_frame_is_durable_before_consumer_receives_it(db, owner, monkeypatch):
    from app.ai_chat import router
    _, session, pair = turn(db, owner)
    def source(*args, **kwargs):
        yield {'type': 'delta', 'text': 'durable first frame'}
        yield {'type': 'done'}
    monkeypatch.setattr(router, 'chat_stream', source)
    events = router.stream_assistant_events(db, owner.id, session.id, pair.assistant_message, reused=False)
    try:
        while b'event: delta' not in next(events):
            pass
        db.refresh(pair.assistant_message)
        assert pair.assistant_message.content == 'durable first frame'
        assert pair.assistant_message.first_token_ms is not None
    finally:
        events.close()


def test_process_exit_preserves_checkpoint_for_reopened_session(tmp_path):
    """A child exits without cleanup; another DB session recovers its saved text."""
    import subprocess
    import sys
    from sqlalchemy import MetaData, create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    from app.auth.models import ArkUser
    path = tmp_path / 'restart.db'
    engine = create_engine(f'sqlite:///{path}')
    metadata = MetaData()
    for name in ('ark_users', 'ark_roles', 'ark_permissions', 'ark_user_roles', 'ark_role_permissions',
                 'ark_ai_providers', 'ark_ai_presets', 'ark_ai_call_logs', 'ark_ai_chat_sessions',
                 'ark_ai_chat_messages', 'ark_ai_chat_attachments', 'ark_ai_chat_role_limits'):
        Base.metadata.tables[name].to_metadata(metadata)
    metadata.create_all(engine)
    try:
        with Session(engine) as db:
            user = ArkUser(username='restart', password_hash='test', real_name='Restart')
            db.add(user)
            db.commit()
            session = service.create_session(db, user.id)
            pair = service.begin_turn(db, user.id, session.id, request(None, 'restart_request'))
            owner_id, message_id = user.id, pair.assistant_message.id
        script = '''
import os, sys
import tests.conftest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.ai_chat.generation_service import checkpoint
with Session(create_engine('sqlite:///' + sys.argv[1])) as db:
    checkpoint(db, int(sys.argv[2]), int(sys.argv[3]), 'saved before hard exit', 'saved reasoning')
os._exit(23)
'''
        child = subprocess.run([sys.executable, '-c', script, str(path), str(owner_id), str(message_id)],
                               capture_output=True, text=True, timeout=30)
        assert child.returncode == 23, child.stderr
        with Session(engine, autoflush=False) as db:
            row = db.get(AiChatMessage, message_id)
            assert row.content == 'saved before hard exit' and row.status == 'streaming'
            row.lease_expires_at = beijing_now() - timedelta(seconds=1)
            db.commit()
        with Session(engine) as db:
            assert generation.recover_expired(db, owner_id) == 1
            row = db.get(AiChatMessage, message_id)
            assert (row.status, row.content, row.reasoning_content) == ('failed', 'saved before hard exit', 'saved reasoning')
    finally:
        engine.dispose()
