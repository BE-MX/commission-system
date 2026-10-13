import json

import pytest

from app.customer import pcw_conversation_service as pcw, agent_service
from app.customer.models import CustomerMessage, CustomerSourceRecord, CustomerProfileVersion, CustomerAssignment
from app.auth.models import ArkUser
from app.customer.pcw_models import ConversationBinding
from app.core.time import beijing_now
from app.whatsapp import event_sync, lifecycle, access
from app.whatsapp.models import WhatsAppConversation, WhatsAppMessage, WhatsAppPullCursor
from tests.test_whatsapp_baileys_sync import account, msg, page, stub
from tests.test_pcw_conversation import _bind, _enable_ai
from tests.test_pcw_conversation import _succeeded_job_with_fact, _customer_with_owner
from tests.test_customer_workflow import _user, _grant_permission, _account


@pytest.fixture
def binding(db, account):
    customer, _version = _account(db, code='C-SYNC')
    owner = db.get(ArkUser, account.ark_user_id)
    _grant_permission(db, owner.id, 'customer:read')
    _grant_permission(db, owner.id, 'customer:write')
    db.add(CustomerAssignment(customer_id=customer.id, user_id=owner.id, assignment_role='primary',
        assignment_status='active', assignment_source='manual', effective_from=beijing_now(), operated_by=owner.id))
    account.crm_shared = True; account.ai_egress_allowed = True
    conv = WhatsAppConversation(account_uid=account.account_uid, conversation_uid='wa_test:test@c.us', chat_id='test@c.us')
    db.add(conv); db.flush()
    _bind(db, owner, account.account_uid, conv.conversation_uid, customer.id)
    db.commit()
    return db.query(ConversationBinding).filter_by(source_account_key=account.account_uid).one()


def test_production_no_autoflush_projects_new_message_and_revision(db, account, binding, monkeypatch):
    db.autoflush = False
    original = msg()
    stub(monkeypatch, page(account, [original]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    projected = db.query(CustomerMessage).one()
    stable_uid = db.query(WhatsAppMessage).one().message_uid
    source_id = projected.source_record_id
    changed = msg(revision=2); changed['sender_name'] = 'updated synthetic sender'
    stub(monkeypatch, page(account, [changed]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    assert db.query(CustomerMessage).count() == 1
    assert projected.external_message_id == stable_uid
    assert projected.source_record_id != source_id
    assert db.get(CustomerSourceRecord, source_id).processing_status == 'superseded'
    revoked = msg(revision=3, deleted=True)
    stub(monkeypatch, page(account, [revoked]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    assert projected.content_text is None
    assert projected.attachment_meta_json == []


def test_agent_read_all_needs_source_grant_and_current_sharing(db, account, binding, monkeypatch):
    stub(monkeypatch, page(account, [msg()]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    reader = _user(db, 9702); _grant_permission(db, reader.id, 'customer:read_all'); db.commit()
    actor = {'sub': str(reader.id), 'roles': [], 'permissions': ['customer:read_all']}
    result = agent_service.search_customer_messages(db, user=actor, customer_id=binding.customer_id)
    assert result['items'] == []
    owner = {'sub': str(account.ark_user_id), 'roles': [], 'permissions': ['customer:read']}
    assert len(agent_service.search_customer_messages(db, user=owner, customer_id=binding.customer_id)['items']) == 1
    account.crm_shared = False; db.commit()
    assert agent_service.search_customer_messages(db, user=owner, customer_id=binding.customer_id)['items'] == []


def test_analysis_revocation_during_model_call_does_not_publish(db, account, binding, monkeypatch):
    _enable_ai(monkeypatch)
    stub(monkeypatch, page(account, [msg()]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    created = pcw.create_analysis_job(db, conversation_id=binding.projected_conversation_id,
        actor_user_id=account.ark_user_id, actor_permissions=['customer:read'])
    def model(**kwargs):
        account.consent_state = 'paused'; account.ai_egress_allowed = False; account.consent_version += 1
        db.commit()
        return {'content': json.dumps({'summary': 'synthetic summary', 'demands': [], 'objections': [],
            'commitments': [], 'open_questions': [], 'next_steps': [], 'profile_candidates': []})}
    job = pcw.run_analysis_job(db, job_id=created['id'], chat_fn=model)
    assert job.status == 'failed' and job.failure_reason == 'AI_AUTH_REVOKED'
    assert job.result_analysis_id is None


def test_explicit_owner_phone_confirmation_is_not_an_admin_attestation(db, account):
    account.status = 'revoke_pending'; account.consent_state = 'revoked'; db.commit()
    admin = _user(db, 9703); _grant_permission(db, admin.id, 'whatsapp:write'); _grant_permission(db, admin.id, 'whatsapp:admin'); db.commit()
    with pytest.raises(PermissionError):
        lifecycle.confirm_phone_removal(db, account.account_uid, {'sub': str(admin.id)}, phone_device_removed=True)
    db.rollback()
    result = lifecycle.confirm_phone_removal(db, account.account_uid, {'sub': str(account.ark_user_id)}, phone_device_removed=True)
    assert result.status == 'revoked' and result.raw_payload['revoke_state'] == 'owner_confirmed'


@pytest.mark.parametrize('bad', [{'source_revision': {'invalid': 1}}, {'source_key': {'remoteJid': 42, 'id': 'bad', 'fromMe': False}},
    {'content_text': {'invalid': 'text'}}, {'content_preview': {}}, {'direction': []}, {'attachments': [{'file_size': {}}]}])
def test_poison_field_type_does_not_block_following_event(db, account, monkeypatch, bad):
    invalid = msg('bad'); invalid.update(bad)
    stub(monkeypatch, page(account, [invalid, msg('valid')]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    assert db.query(WhatsAppMessage).count() == 1
    assert db.query(WhatsAppPullCursor).one().cursor_value == 'event_cursor_2'


def test_positive_missing_bind_readback_allows_next_explicit_retry(db, account, monkeypatch):
    from app.whatsapp.connector_client import ConnectorError
    calls = []
    class Client:
        def create_bind_session(self, user_id, **operation):
            calls.append('post')
            if len(calls) == 1:
                raise ConnectorError('network refusal')
            return {**operation, 'ark_user_id': user_id, 'status': 'pending'}
        def get_bind_session(self, uid):
            calls.append('get'); raise ConnectorError('not found', status_code=404)
    monkeypatch.setattr(lifecycle, 'WhatsAppConnectorClient', Client)
    actor = {'sub': str(account.ark_user_id)}
    with pytest.raises(ValueError):
        lifecycle.bind(db, actor, account_uid=account.account_uid, company_account=True, crm_shared=False)
    result = lifecycle.bind(db, actor, account_uid=account.account_uid, company_account=True, crm_shared=False)
    assert calls == ['post', 'get', 'post']
    assert result.account_uid == account.account_uid


def test_immutable_profile_and_agent_context_hide_revoked_whatsapp_facts(db, monkeypatch):
    from types import SimpleNamespace
    from app.whatsapp.derived_access import filter_snapshot
    from app.customer.models import CustomerFact
    from app.insight.customer_profile_service import get_profile
    customer, owner = _customer_with_owner(db, code='C-DERIVED', user_id=9801)
    source_account, _binding, _job = _succeeded_job_with_fact(db, monkeypatch, customer, owner, tag='derived')
    fact = db.query(CustomerFact).filter_by(customer_id=customer.id, fact_key='preference.expressed.color').one()
    payload = {'preferences': {'expressed': [{'fact_id': fact.id, 'value': 'synthetic private preference'}]},
        'current_needs': [{'fact_id': fact.id, 'value': 'synthetic private preference'}],
        'recommended_actions': {'items': [{'title': 'Quote synthetic private preference', 'evidence_fact_ids': [fact.id]}]},
        'risks': {'items': [{'title': 'Derived synthetic private risk', 'evidence_fact_ids': [fact.id]}]},
        'evidence_refs': [{'fact_id': fact.id}]}
    version = db.get(CustomerProfileVersion, customer.current_profile_version_id)
    version.profile_json = payload; version.evidence_fact_ids = [fact.id]; db.commit()
    def rights(actor_id):
        return SimpleNamespace(actor_user_id=actor_id, can_manage=True, max_data_classification='restricted_internal', allows_visibility=lambda scope: True)
    reader = _user(db, 9802); db.commit()
    owner_view, ids = filter_snapshot(db, payload, version, access=rights(owner.id))
    assert owner_view['preferences']['expressed'][0]['value'] == 'synthetic private preference'
    assert ids == [fact.id]
    admin_view = get_profile(db, customer.id, access=rights(reader.id))
    assert admin_view['profile_json']['preferences']['redacted']
    assert 'synthetic private preference' not in json.dumps(admin_view['profile_json'])
    assert admin_view['profile_json']['recommended_actions']['items'] == []
    assert admin_view['profile_json']['risks']['items'] == []
    source_account.crm_shared = False; db.commit()
    hidden, ids = filter_snapshot(db, payload, version, access=rights(owner.id))
    assert hidden['current_needs']['redacted'] and ids == []
    assert version.profile_json == payload  # Immutable history was not overwritten.


def test_customer_scope_withdrawn_during_model_call_does_not_publish(db, account, binding, monkeypatch):
    _enable_ai(monkeypatch)
    stub(monkeypatch, page(account, [msg()]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    created = pcw.create_analysis_job(db, conversation_id=binding.projected_conversation_id,
        actor_user_id=account.ark_user_id, actor_permissions=['customer:read'])
    def model(**kwargs):
        db.query(CustomerAssignment).filter_by(customer_id=binding.customer_id, user_id=account.ark_user_id).update({'assignment_status': 'inactive'})
        db.commit()
        return {'content': json.dumps({'summary': 'synthetic summary', 'demands': [], 'objections': [],
            'commitments': [], 'open_questions': [], 'next_steps': [], 'profile_candidates': []})}
    job = pcw.run_analysis_job(db, job_id=created['id'], chat_fn=model)
    assert job.status == 'failed' and job.failure_reason == 'AI_AUTH_REVOKED'
    assert job.result_analysis_id is None


def test_existing_agent_run_requires_separate_egress_permission(db, account, binding, monkeypatch):
    from tests.test_customer_agent_tools import _membership, _identity
    stub(monkeypatch, page(account, [msg()]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    _membership(db, binding.customer_id, run_id=501)
    actor = _identity(binding.customer_id, run_id=501); actor['sub'] = str(account.ark_user_id)
    account.ai_egress_allowed = False; db.commit()
    assert agent_service.search_customer_messages(db, user=actor, customer_id=binding.customer_id)['items'] == []
    account.ai_egress_allowed = True; db.commit()
    assert len(agent_service.search_customer_messages(db, user=actor, customer_id=binding.customer_id)['items']) == 1
