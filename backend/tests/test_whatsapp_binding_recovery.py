from types import SimpleNamespace

import pytest

from app.whatsapp import lifecycle, service
from app.whatsapp.models import WhatsAppBindSession
from tests.test_whatsapp_baileys_sync import account  # noqa: F401


def pending(db, account):
    row = WhatsAppBindSession(bind_session_uid='bind_old', account_uid=account.account_uid,
        ark_user_id=account.ark_user_id, status='pending', qr_code_url='obsolete-qr')
    db.add(row)
    db.commit()
    return row


def test_revoke_closes_pending_binding_before_remote_logout(db, account, monkeypatch):
    row = pending(db, account)
    def revoke(uid):
        assert row.status == 'revoking'
        assert row.qr_code_url is None and row.expires_at is None
        return {'revoke_state': 'remote_confirmed'}
    monkeypatch.setattr(lifecycle, 'WhatsAppConnectorClient', lambda: SimpleNamespace(revoke_account=revoke))
    lifecycle.revoke(db, account.account_uid, {'sub': str(account.ark_user_id)})
    assert row.status not in ('pending', 'binding')


@pytest.mark.parametrize('rebind', [False, True])
@pytest.mark.parametrize('status,consent', [('revoke_pending', 'revoked'), ('paused', 'paused'), ('paused', 'active')])
def test_historical_stopped_pending_does_not_block_explicit_binding(db, account, monkeypatch, rebind, status, consent):
    row = pending(db, account)
    account.status, account.consent_state = status, consent
    db.commit()
    old_version = account.consent_version
    calls = []
    def create(user_id, **operation):
        calls.append(operation)
        assert operation['bind_session_uid'] != row.bind_session_uid
        return {**operation, 'ark_user_id': user_id, 'status': 'pending'}
    monkeypatch.setattr(lifecycle, 'WhatsAppConnectorClient', lambda: SimpleNamespace(create_bind_session=create))
    result = lifecycle.bind(db, {'sub': str(account.ark_user_id)},
        account_uid=account.account_uid if rebind else None, company_account=True, crm_shared=False)
    assert len(calls) == 1 and result.bind_session_uid != row.bind_session_uid
    assert row.status == status and row.qr_code_url is None
    if not rebind:
        assert account.consent_state == consent and account.consent_version == old_version


def test_revoked_pending_status_is_read_locally_without_connector(db, account, monkeypatch):
    row = pending(db, account)
    account.status, account.consent_state = 'revoke_pending', 'revoked'
    db.commit()
    monkeypatch.setattr(service, 'WhatsAppConnectorClient', lambda: SimpleNamespace())
    result = service.refresh_bind_session(db, row.bind_session_uid)
    assert result.status == 'revoke_pending'
    assert result.qr_code_url is None and result._transient_qr is None
