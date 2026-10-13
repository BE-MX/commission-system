from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.auth.models import ArkUser
from app.whatsapp import access, event_sync, identity, lifecycle, service
from app.whatsapp.models import WhatsAppAccount, WhatsAppMessage, WhatsAppMessageSource, WhatsAppPullCursor, WhatsAppBodyGrant, WhatsAppBindSession
from tests.test_customer_workflow import _user, _grant_permission


@pytest.fixture
def account(db):
    owner = _user(db, 9601)
    _grant_permission(db, owner.id, 'whatsapp:read')
    _grant_permission(db, owner.id, 'whatsapp:write')
    row = WhatsAppAccount(account_uid='wa_test', ark_user_id=owner.id, provider='baileys', status='active',
        consent_state='active', consent_version=3, session_generation=2, crm_shared=False)
    db.add(row); db.commit()
    return row


def msg(key='a', *, participant=None, from_me=False, jid='test@s.whatsapp.net', revision=1, deleted=False):
    return {'account_uid': 'wa_test', 'source_key': {'remoteJid': jid, 'id': key, 'fromMe': from_me, 'participant': participant},
        'source_revision': revision, 'direction': 'outbound' if from_me else 'inbound',
        'content_type': 'text', 'content_text': 'synthetic test content', 'sent_at': '2026-10-12T16:00:00Z',
        'deleted_at': '2026-10-12T16:00:05Z' if deleted else None, 'attachments': []}


def page(account, payloads):
    return {'items': [{'sequence': n + 1, 'kind': 'message', 'payload': payload} for n, payload in enumerate(payloads)],
        'next_cursor': 'event_cursor_2', 'has_more': False, 'account': {'account_uid': account.account_uid,
        'ark_user_id': account.ark_user_id, 'session_generation': account.session_generation,
        'consent_version': str(account.consent_version), 'status': 'active', 'connection_state': 'online'}}


def stub(monkeypatch, data):
    monkeypatch.setattr(event_sync, 'WhatsAppConnectorClient', lambda: SimpleNamespace(pull_changes=lambda *args: deepcopy(data)))


def test_overlap_same_second_late_arrival_and_replay(db, account, monkeypatch):
    items = [msg('a'), msg('b'), msg('a')]
    items[1]['sent_at'] = '2026-10-11T16:00:00Z'  # late arrival has older event time
    stub(monkeypatch, page(account, items))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    assert db.query(WhatsAppMessage).count() == 2
    assert db.query(WhatsAppMessageSource).count() == 2
    assert db.query(WhatsAppPullCursor).one().cursor_value == 'event_cursor_2'
    assert db.query(WhatsAppMessage).filter_by(external_message_id='bai_' + db.query(WhatsAppMessageSource).first().source_digest).first().sent_at == datetime(2026, 10, 13, 0, 0)


def test_transaction_failure_does_not_advance_cursor(db, account, monkeypatch):
    stub(monkeypatch, page(account, [msg()]))
    monkeypatch.setattr(service, '_upsert_message', lambda *args: (_ for _ in ()).throw(RuntimeError('injected storage failure')))
    with pytest.raises(RuntimeError):
        event_sync.pull_changes(db, account.account_uid, 100)
    db.rollback()
    assert db.query(WhatsAppMessage).count() == 0
    assert db.query(WhatsAppPullCursor).count() == 0


def test_tombstone_before_history_never_revives(db, account, monkeypatch):
    stub(monkeypatch, page(account, [msg(revision=2, deleted=True), msg(revision=1)]))
    event_sync.pull_changes(db, account.account_uid, 100); db.commit()
    row = db.query(WhatsAppMessage).one()
    assert row.deleted_at and row.content_text is None and row.content_preview is None
    assert row.source_revision == 2
    assert row.raw_payload['content_text'] is None


def test_edited_content_resists_old_append(db, account, monkeypatch):
    latest = msg(revision=4); latest['content_text'] = 'edited synthetic text'
    stub(monkeypatch, page(account, [latest, msg(revision=3)]))
    event_sync.pull_changes(db, account.account_uid, 100)
    assert db.query(WhatsAppMessage).one().content_text == 'edited synthetic text'


def test_complete_source_key_separates_group_participants_and_directions(db, account):
    for payload in [msg(jid='group@g.us', participant='one@s.whatsapp.net'), msg(jid='group@g.us', participant='two@s.whatsapp.net'), msg(from_me=True)]:
        service._upsert_message(db, account.account_uid, identity.resolve_message(db, account.account_uid, payload))
        db.flush()
    assert db.query(WhatsAppMessage).count() == 3


def test_verified_legacy_direct_key_keeps_message_uid(db, account):
    old = WhatsAppMessage(message_uid='preserved-old-uid', account_uid=account.account_uid,
        external_message_id='false_test@c.us_a', direction='inbound', content_text='old')
    db.add(old); db.flush()
    resolved = identity.resolve_message(db, account.account_uid, msg())
    assert resolved['message_uid'] == old.message_uid
    assert resolved['external_message_id'] == old.external_message_id
    assert resolved['identity_state'] == 'exact'


def test_lid_alias_is_not_phone_or_guess_match(db, account):
    payload = msg(jid='unknown@lid')
    result = identity.resolve_message(db, account.account_uid, payload)
    assert result['identity_state'] == 'unverified'
    assert result['source_key']['remoteJid'] == 'unknown@lid'


@pytest.mark.parametrize('field,value', [('consent_version', 1), ('session_generation', 1), ('ark_user_id', 99)])
def test_stale_or_wrong_account_feed_denied(db, account, monkeypatch, field, value):
    data = page(account, [msg()]); data['account'][field] = value
    stub(monkeypatch, data)
    with pytest.raises((PermissionError, ValueError)):
        event_sync.pull_changes(db, account.account_uid, 100)
    assert db.query(WhatsAppMessage).count() == 0


def test_owner_disabled_during_fetch_denies_commit(db, account, monkeypatch):
    data = page(account, [msg()])
    def fetch(*args):
        db.get(ArkUser, account.ark_user_id).is_active = False
        db.flush()
        return data
    monkeypatch.setattr(event_sync, 'WhatsAppConnectorClient', lambda: SimpleNamespace(pull_changes=fetch))
    with pytest.raises(PermissionError):
        event_sync.pull_changes(db, account.account_uid, 100)
    db.rollback()
    assert db.query(WhatsAppMessage).count() == 0


def test_disabled_callback_is_sticky_after_employee_reactivation(db, account):
    owner = db.get(ArkUser, account.ark_user_id); owner.is_active = False; db.commit()
    assert access.authorization_snapshot(db, account.account_uid)['allowed'] is False
    owner.is_active = True; db.commit()
    assert access.authorization_snapshot(db, account.account_uid)['allowed'] is False
    assert account.consent_state == 'paused'


def test_explicit_reader_grant_expires_with_version(db, account):
    reader = _user(db, 9602); _grant_permission(db, reader.id, 'whatsapp:read')
    db.add(WhatsAppBodyGrant(account_uid=account.account_uid, user_id=reader.id, consent_version=account.consent_version)); db.flush()
    access.require_body(db, account, reader.id)
    account.consent_version += 1; db.flush()
    with pytest.raises(PermissionError):
        access.require_body(db, account, reader.id)


def test_qr_never_persisted(db, account):
    session = service._upsert_bind_session(db, {'bind_session_uid': 'bind_test', 'account_uid': account.account_uid,
        'ark_user_id': account.ark_user_id, 'status': 'pending', 'qr_code_url': 'synthetic-qr', 'expires_at': '2026-10-13T00:01:00+08:00'}, account.ark_user_id)
    db.commit()
    assert session.qr_code_url is None
    assert 'qr_code_url' not in session.last_payload
    assert getattr(session, '_transient_qr') == 'synthetic-qr'


def test_stale_bind_status_cannot_replace_owner_phone_confirmation(db, account):
    stale = {'account_uid': account.account_uid, 'ark_user_id': account.ark_user_id, 'status': 'active',
        'session_generation': account.session_generation, 'consent_version': account.consent_version}
    account.status = 'revoked'; account.consent_state = 'revoked'; account.consent_version += 1
    account.raw_payload = {'revoke_state': 'owner_confirmed'}; db.commit()
    service._upsert_account(db, stale, account.ark_user_id)
    assert account.status == 'revoked' and account.raw_payload['revoke_state'] == 'owner_confirmed'


def test_stale_cached_account_is_refreshed_before_status_readback(db, account):
    from sqlalchemy.orm import Session
    account.status = 'binding'; db.commit()
    stale = {'account_uid': account.account_uid, 'ark_user_id': account.ark_user_id, 'status': 'active',
        'session_generation': account.session_generation, 'consent_version': account.consent_version}
    assert account.status == 'binding'
    with Session(bind=db.get_bind()) as second:
        current = second.query(WhatsAppAccount).filter_by(account_uid=account.account_uid).one()
        current.status = 'revoke_pending'; current.consent_state = 'revoked'; current.consent_version += 1
        second.commit()
    assert account.status == 'binding'  # ORM cache contains a stale object.
    service._upsert_account(db, stale, account.ark_user_id)
    db.commit()
    assert account.status == 'revoke_pending' and account.consent_state == 'revoked'


def test_revoke_unknown_remote_stays_pending_and_no_second_post(db, account, monkeypatch):
    from app.whatsapp.connector_client import ConnectorError
    calls = []
    class Client:
        def revoke_account(self, uid):
            calls.append(uid)
            assert db.get(WhatsAppAccount, account.id).consent_state == 'revoked'
            raise ConnectorError('uncertain')
        def get_account(self, uid):
            return {'status': 'revoked'}  # status alone is not proof of remote logout
    monkeypatch.setattr(lifecycle, 'WhatsAppConnectorClient', Client)
    result = lifecycle.revoke(db, account.account_uid, {'sub': str(account.ark_user_id)})
    assert result.status == 'revoke_pending'
    assert calls == [account.account_uid]


def test_bind_timeout_reads_exact_reserved_operation_once(db, account, monkeypatch):
    from app.whatsapp.connector_client import ConnectorError
    calls = []
    class Client:
        def create_bind_session(self, user_id, **operation):
            calls.append(('post', operation))
            assert db.query(WhatsAppBindSession).filter_by(bind_session_uid=operation['bind_session_uid']).one()
            raise ConnectorError('timeout')
        def get_bind_session(self, uid):
            calls.append(('get', uid))
            return {'bind_session_uid': uid, 'account_uid': account.account_uid, 'ark_user_id': account.ark_user_id, 'status': 'pending'}
    monkeypatch.setattr(lifecycle, 'WhatsAppConnectorClient', Client)
    result = lifecycle.bind(db, {'sub': str(account.ark_user_id)}, account_uid=account.account_uid, company_account=True, crm_shared=False)
    assert result.account_uid == account.account_uid
    assert [call[0] for call in calls] == ['post', 'get']
    assert calls[0][1]['bind_session_uid'] == calls[1][1]


def test_automatic_sync_reads_protected_pause_metadata_after_feed_rejection(db, account, monkeypatch):
    from app.whatsapp.connector_client import ConnectorError
    class Client:
        def pull_changes(self, *args):
            raise ConnectorError('account_paused', status_code=403)
        def get_account(self, uid):
            return {'account_uid': uid, 'ark_user_id': account.ark_user_id,
                'session_generation': account.session_generation, 'consent_version': account.consent_version,
                'status': 'paused', 'connector_status': 'protected_pause', 'last_error_code': 'disk_capacity',
                'needs_user_action': True, 'coverage': {'gap_reason': 'disk_capacity'}}
    monkeypatch.setattr(event_sync, 'WhatsAppConnectorClient', Client)
    monkeypatch.setattr(service, 'WhatsAppConnectorClient', Client)
    stats = service.auto_sync_accounts(db, provider='baileys')
    assert stats['error'] == 1
    assert account.status == 'paused' and account.connector_status == 'protected_pause'
    assert account.raw_payload['gap_reason'] == 'disk_capacity' and account.raw_payload['needs_user_action']
