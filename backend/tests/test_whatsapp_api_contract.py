from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.whatsapp import router as module, event_sync
from app.whatsapp.models import WhatsAppBodyGrant
from tests.test_whatsapp_baileys_sync import account, msg, page, stub
from tests.test_customer_workflow import _user, _grant_permission


@pytest.fixture
def client(db, account, monkeypatch):
    app = FastAPI(); app.include_router(module.router, prefix='/api/whatsapp')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {'sub': str(account.ark_user_id), 'permissions': ['whatsapp:read', 'whatsapp:write'], 'roles': []}
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(WHATSAPP_CONNECTOR_API_KEY='synthetic-service-key'))
    with TestClient(app) as test_client:
        yield test_client


def test_machine_callback_fails_closed_and_returns_no_body(client, account):
    path = f'/api/whatsapp/internal/accounts/{account.account_uid}/authorization'
    assert client.get(path).status_code in (401, 403)
    assert client.get(path, headers={'Authorization': 'Bearer wrong'}).status_code == 403
    result = client.get(path, headers={'Authorization': 'Bearer synthetic-service-key'})
    assert result.status_code == 200 and result.json()['data']['allowed']
    assert set(result.json()['data']) == {'allowed', 'ark_user_id', 'provider', 'session_generation', 'consent_version', 'crm_shared'}


def test_v1_sync_count_and_pagination_envelope_retained(client, account, monkeypatch):
    stub(monkeypatch, page(account, [msg()]))
    result = client.post('/api/whatsapp/sync/pull', json={'account_uid': account.account_uid, 'resource': 'messages', 'limit': 100})
    assert result.status_code == 200
    assert result.json()['data'] == {'account_uid': account.account_uid, 'resource': 'messages', 'pulled': 1, 'next_cursor': None}
    messages = client.get('/api/whatsapp/messages', params={'account_uid': account.account_uid, 'page': 1, 'page_size': 20}).json()['data']
    assert set(messages) == {'items', 'total', 'page', 'page_size'}
    assert messages['total'] == 1 and len(messages['items']) == 1


def test_bind_without_company_consent_never_calls_connector(client, monkeypatch):
    monkeypatch.setattr(module.lifecycle, 'WhatsAppConnectorClient', lambda: (_ for _ in ()).throw(AssertionError('unexpected connector request')))
    assert client.post('/api/whatsapp/bind-sessions', json={}).status_code == 400


@pytest.mark.parametrize('server_zone', ['UTC', 'America/New_York'])
def test_external_time_uses_beijing_midnight_under_other_server_zones(monkeypatch, server_zone):
    from app.whatsapp.payload import parse_dt
    monkeypatch.setenv('TZ', server_zone)
    assert parse_dt('2026-10-12T16:00:00Z').isoformat() == '2026-10-13T00:00:00'
    assert parse_dt('2026-10-12T12:00:00-04:00').isoformat() == '2026-10-13T00:00:00'
