import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.ai.models import AiPreset, AiProvider
from app.auth.models import ArkUser
from app.whatsapp import assistant_service as assistant
from app.whatsapp.models import WhatsAppConversation, WhatsAppMessage
from tests.test_whatsapp_baileys_sync import account
from tests.test_customer_workflow import _user, _grant_permission


@pytest.fixture
def scope(db, account, monkeypatch):
    account.ai_egress_allowed = True
    provider = AiProvider(name='synthetic-assistant', provider_type='direct', api_type='openai',
        api_base='https://synthetic.invalid', api_key='not-a-real-key', is_enabled=True, timeout_sec=10)
    db.add(provider); db.flush()
    db.add(AiPreset(preset_name='whatsapp_message_assistant', provider_id=provider.id, model='synthetic',
        is_enabled=True, parameters={'max_tokens': 4096}))
    conv = WhatsAppConversation(account_uid=account.account_uid, conversation_uid='conv-a', chat_id='a@g.us',
        contact_name='Synthetic A', is_group=True, history_state='partial')
    db.add(conv)
    for n, minute in enumerate((0, 1, 2)):
        db.add(WhatsAppMessage(account_uid=account.account_uid, conversation_uid='conv-a', message_uid=f'm{n}',
            external_message_id=f'e{n}', direction='inbound', content_type='text', content_text=f'synthetic {n}',
            sent_at=datetime(2026, 10, 13, 0, minute), source_revision=1))
    db.commit()
    return account


def create(db, scope, key='request-one', **kwargs):
    return assistant.create_run(db, scope.ark_user_id, account_uid=scope.account_uid,
        start_at=datetime.fromisoformat('2026-10-12T16:00:00+00:00'),
        end_at=datetime.fromisoformat('2026-10-13T00:01:00+08:00'),
        client_request_uid=key, **kwargs)


def output(**kwargs):
    data = json.loads(kwargs['messages'][-1]['content'])
    ids = data['message_uids']
    return {'content': json.dumps({'summary': 'Synthetic summary', 'open_questions': ['Need confirmation'],
        'follow_up_suggestions': [{'text': 'Confirm need', 'message_uids': ids[:1], 'knowledge_source_ids': []}],
        'tasks': [{'title': 'Confirm requirement', 'description': 'Ask for clarification', 'priority': 'P2',
            'due_date': None, 'message_uids': ids[:1], 'knowledge_source_ids': []}]})}


def test_range_inclusive_beijing_midnight_and_not_ui_page(db, scope):
    run = create(db, scope)
    assert run.message_count == 2 and run.conversation_count == 1
    assert run.start_at == datetime(2026, 10, 13)
    assistant.execute_run(db, run.run_uid, chat_fn=output)
    data = assistant.get_run(db, scope.ark_user_id, run.run_uid)
    assert data['status'] == 'succeeded'
    assert data['results'][0]['is_group'] and data['results'][0]['message_count'] == 2
    assert '知识' in ' '.join(data['warnings'])
    assert 'metadata' == data['audit']['snapshot_mode']


def test_idempotency_and_slot_prevent_repeat_model_calls(db, scope):
    run = create(db, scope)
    assert create(db, scope).run_uid == run.run_uid
    with pytest.raises(assistant.AssistantConflict):
        create(db, scope, key='other')
    db.rollback()
    calls = []
    def counted(**kwargs):
        calls.append(1); return output(**kwargs)
    assistant.execute_run(db, run.run_uid, chat_fn=counted)
    assistant.execute_run(db, run.run_uid, chat_fn=counted)
    assert len(calls) == 1


def test_model_revoke_or_message_edit_cannot_publish(db, scope):
    run = create(db, scope)
    def changed(**kwargs):
        message = db.query(WhatsAppMessage).filter_by(message_uid='m0').one()
        message.source_revision += 1; message.content_text = 'edited'; db.commit()
        return output(**kwargs)
    assistant.execute_run(db, run.run_uid, chat_fn=changed)
    assert assistant.get_run(db, scope.ark_user_id, run.run_uid)['status'] == 'stale'
    assert run.result_json is None


def test_live_body_scope_egress_independent_crm_and_private_results(db, scope):
    assert scope.crm_shared is False
    run = create(db, scope)
    assistant.execute_run(db, run.run_uid, chat_fn=output)
    other = _user(db, 9881); _grant_permission(db, other.id, 'whatsapp:read'); db.commit()
    with pytest.raises((PermissionError, LookupError)):
        assistant.get_run(db, other.id, run.run_uid)
    scope.ai_egress_allowed = False; db.commit()
    with pytest.raises(PermissionError):
        create(db, scope, key='not-authorized')


def test_unknown_model_refs_rejected_and_no_partial_results(db, scope):
    run = create(db, scope)
    def wrong(**kwargs):
        result = json.loads(output(**kwargs)['content'])
        result['tasks'][0]['message_uids'] = ['not-present']
        return {'content': json.dumps(result)}
    assistant.execute_run(db, run.run_uid, chat_fn=wrong)
    assert run.status == 'failed' and run.result_json is None
    assert run.error_code == 'INVALID_MODEL_OUTPUT'


def test_checklist_persists_without_task_center_and_old_source_is_blocked(db, scope):
    from app.task.models import TaskItem
    run = create(db, scope)
    assistant.execute_run(db, run.run_uid, chat_fn=output)
    data = assistant.get_run(db, scope.ark_user_id, run.run_uid)
    uid = data['results'][0]['tasks'][0]['task_uid']
    updated = assistant.update_task(db, scope.ark_user_id, run.run_uid, uid, completed=True)
    assert updated['results'][0]['tasks'][0]['completed'] is True
    assert db.query(TaskItem).count() == 0
    scope.consent_version += 1; db.commit()
    stale = assistant.get_run(db, scope.ark_user_id, run.run_uid)
    assert stale['status'] == 'stale' and not stale['results']
    with pytest.raises(assistant.AssistantConflict):
        assistant.update_task(db, scope.ark_user_id, run.run_uid, uid, completed=False)


@pytest.mark.parametrize('zone', ['UTC', 'America/New_York'])
def test_range_requires_offset_and_uses_beijing_not_server_clock(db, scope, monkeypatch, zone):
    monkeypatch.setenv('TZ', zone)
    run = create(db, scope)
    assert run.start_at == datetime(2026, 10, 13)
    with pytest.raises(ValueError):
        assistant.normalize_range(datetime(2026, 10, 13), datetime(2026, 10, 14))


def test_real_uid_length_with_hundreds_of_messages_uses_compact_citations(db, scope):
    import hashlib
    db.query(WhatsAppMessage).delete()
    expected = set()
    for index in range(302):
        uid = f'wa_acc_0123456789abcdef0123456789abcdef:bai_{hashlib.sha256(str(index).encode()).hexdigest()}'
        expected.add(uid)
        db.add(WhatsAppMessage(account_uid=scope.account_uid, conversation_uid='conv-a', message_uid=uid,
            external_message_id=f'real_shape_{index}', direction='inbound', content_type='text', content_text='x',
            sent_at=datetime(2026, 10, 13), source_revision=1))
    db.commit()
    run = create(db, scope)
    calls = []
    def model(**kwargs):
        payload = json.loads(kwargs['messages'][-1]['content'])
        assert len(kwargs['messages'][-1]['content']) <= 32000
        assert all(len(ref) < 8 for ref in payload['message_uids'])
        assert kwargs['snapshot_mode'] == 'metadata'
        calls.append(payload)
        return output(**kwargs)
    assistant.execute_run(db, run.run_uid, chat_fn=model)
    data = assistant.get_run(db, scope.ark_user_id, run.run_uid)
    assert data['status'] == 'succeeded' and data['message_count'] == 302
    assert 1 < len(calls) <= 20
    actual = [message for payload in calls if payload['phase'] == 'analyze' for message in payload['messages']]
    assert len(actual) == 302
    assert set(data['results'][0]['tasks'][0]['message_uids']) <= expected


def test_single_long_message_is_fully_split_and_merged(db, scope):
    text = ''.join(str(index % 10) for index in range(25000))
    row = db.query(WhatsAppMessage).filter_by(message_uid='m0').one()
    row.content_text = text; db.commit()
    run = create(db, scope)
    bodies = []
    def model(**kwargs):
        payload = json.loads(kwargs['messages'][-1]['content'])
        bodies.extend(item['text'] for item in payload.get('messages', []) if item['message_uid'] == 'm0')
        return output(**kwargs)
    assistant.execute_run(db, run.run_uid, chat_fn=model)
    assert run.status == 'succeeded'
    assert ''.join(bodies) == text


def test_body_revoke_during_external_model_call_removes_result(db, scope):
    run = create(db, scope)
    def revoke(**kwargs):
        scope.consent_state = 'paused'; scope.consent_version += 1; db.commit()
        return output(**kwargs)
    assistant.execute_run(db, run.run_uid, chat_fn=revoke)
    assert run.status == 'stale' and run.result_json is None and run.error_code == 'AUTH_CHANGED'
    with pytest.raises(PermissionError):
        assistant.get_run(db, scope.ark_user_id, run.run_uid)


def test_stale_pending_process_frees_slot_without_resending(db, scope):
    from datetime import timedelta
    run = create(db, scope)
    run.created_at -= timedelta(hours=1); db.commit()
    expired = assistant.get_run(db, scope.ark_user_id, run.run_uid)
    assert expired['status'] == 'failed' and expired['error_code'] == 'ANALYSIS_TIMEOUT'
    assistant.execute_run(db, run.run_uid, chat_fn=lambda **kwargs: pytest.fail('must never resend'))
    fresh = create(db, scope, key='explicit-retry')
    assert fresh.run_uid != run.run_uid and fresh.status == 'pending'


def test_excess_range_message_count_and_cross_account_scope_admission(db, scope):
    from datetime import timedelta, timezone
    with pytest.raises(ValueError):
        assistant.normalize_range(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 1, tzinfo=timezone.utc))
    with pytest.raises(LookupError):
        create(db, scope, conversation_uid='other-account-conversation')
    db.rollback()
    db.bulk_save_objects([WhatsAppMessage(account_uid=scope.account_uid, conversation_uid='conv-a',
        message_uid=f'limit_{n}', external_message_id=f'limit_e_{n}', direction='inbound', content_type='text',
        content_text='x', sent_at=datetime(2026, 10, 13)) for n in range(2000)])
    db.commit()
    with pytest.raises(ValueError, match='2000'):
        create(db, scope)


def test_request_identity_cannot_change_range_or_poll_reveal_other_run(db, scope):
    run = create(db, scope)
    with pytest.raises(assistant.AssistantConflict):
        create(db, scope, conversation_uid='conv-a')
    db.rollback()
    with pytest.raises(LookupError):
        assistant.find_request(db, scope.ark_user_id, scope.account_uid, 'not-found')
    assert assistant.find_request(db, scope.ark_user_id, scope.account_uid, 'request-one')['run_uid'] == run.run_uid


@pytest.fixture
def published_knowledge(db, scope):
    from app.knowledge.models import KnowledgeLibrary, KnowledgeLibraryMember
    from tests.test_whatsapp_assistant_knowledge import document
    _grant_permission(db, scope.ark_user_id, 'knowledge:read')
    library = KnowledgeLibrary(name='Synthetic Assistant KB', category='company', created_by=scope.ark_user_id)
    db.add(library); db.flush()
    member = KnowledgeLibraryMember(library_id=library.id, user_id=scope.ark_user_id, role='viewer', created_by=scope.ark_user_id)
    db.add(member)
    row, revision = document(db, 'Synthetic policy', 'Synthetic requirements: confirm details before promising a date.', library_id=library.id)
    db.commit()
    return row, revision, member


def cited_output(**kwargs):
    response = output(**kwargs)
    payload = json.loads(kwargs['messages'][-1]['content'])
    assert payload['knowledge_sources']
    result = json.loads(response['content'])
    ref = payload['knowledge_sources'][0]['source_id']
    result['tasks'][0]['knowledge_source_ids'] = [ref]
    result['follow_up_suggestions'][0]['knowledge_source_ids'] = [ref]
    return {'content': json.dumps(result)}


def test_current_knowledge_citations_and_revision_changes_invalidate_result(db, scope, published_knowledge):
    row, revision, _member = published_knowledge
    run = create(db, scope)
    assistant.execute_run(db, run.run_uid, chat_fn=cited_output)
    result = assistant.get_run(db, scope.ark_user_id, run.run_uid)
    assert result['status'] == 'succeeded'
    source = result['results'][0]['knowledge_sources'][0]
    assert source['document_id'] == row.id and source['revision_id'] == revision.id
    assert 'text' not in run.input_manifest['knowledge_sources'][0]
    row.published_revision_id = None; db.commit()
    changed = assistant.get_run(db, scope.ark_user_id, run.run_uid)
    assert changed['status'] == 'stale' and changed['error_code'] == 'KNOWLEDGE_CHANGED'
    assert not changed['results']


def test_knowledge_membership_revoked_inside_model_does_not_publish(db, scope, published_knowledge):
    _row, _revision, member = published_knowledge
    run = create(db, scope)
    def revoke(**kwargs):
        result = cited_output(**kwargs)
        db.delete(member); db.commit()
        return result
    assistant.execute_run(db, run.run_uid, chat_fn=revoke)
    assert run.status == 'stale' and run.error_code == 'KNOWLEDGE_CHANGED' and run.result_json is None


@pytest.mark.parametrize('different_scope', [False, True])
def test_same_request_terminal_winner_after_expiry_commit_is_reused(db, scope, monkeypatch, different_scope):
    from datetime import timedelta
    from sqlalchemy.orm import sessionmaker
    old = create(db, scope, key='old-slot')
    old.created_at -= timedelta(hours=1); db.commit()
    original_expire = assistant.expire
    winners = []
    def expire_and_interleave(session, run):
        original_expire(session, run)
        if run.run_uid == old.run_uid and not winners:
            with sessionmaker(bind=db.get_bind())() as other:
                account_row = other.get(type(scope), scope.id)
                winner = create(other, account_row, key='next', conversation_uid='conv-a' if different_scope else None)
                assistant.execute_run(other, winner.run_uid, chat_fn=output)
                assert winner.status == 'succeeded'
                winners.append(winner.run_uid)
    monkeypatch.setattr(assistant, 'expire', expire_and_interleave)
    if different_scope:
        with pytest.raises(assistant.AssistantConflict):
            create(db, scope, key='next')
    else:
        repeated = create(db, scope, key='next')
        assert repeated.run_uid == winners[0] and repeated.status == 'succeeded'
    from app.whatsapp.assistant_models import WhatsAppAssistantRun
    assert db.query(WhatsAppAssistantRun).filter_by(client_request_uid='next').count() == 1
