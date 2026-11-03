import httpx
import pytest

from app.invoice import okki_client, customer_picker_service
from tests.test_invoice_customer_filters import _client, bound_user, seed_customers, OKKI_UID


@pytest.mark.parametrize('body,expected', [
    ({'code': 404, 'message': 'Not Found Resource'}, 'missing'),
    ({'code': 200, 'data': {'company_id': 9001, 'name': 'Alpha', 'owner': []}}, 'active'),
])
def test_exact_live_company_identity_and_missing_response(db, monkeypatch, body, expected):
    monkeypatch.setattr(okki_client, 'ensure_access_token', lambda *a, **kw: 'test-token')
    monkeypatch.setattr(okki_client.httpx, 'get', lambda *a, **kw: httpx.Response(200, json=body))
    result = okki_client.get_company_availability(db, 9001)
    assert result['status'] == expected
    assert result['company_id'] == '9001'


@pytest.mark.parametrize('status,body', [
    (403, {'code': 403, 'message': 'Forbidden'}),
    (404, {'code': 404, 'message': 'Not Found Resource'}),
    (200, {'code': 404, 'message': 'Permission denied'}),
    (200, {'code': 200, 'data': {}}),
    (200, {'code': 200, 'data': {'company_id': 9002, 'name': 'Wrong'}}),
])
def test_unavailable_or_unverified_response_is_never_reported_as_missing(db, monkeypatch, status, body):
    monkeypatch.setattr(okki_client, 'ensure_access_token', lambda *a, **kw: 'test-token')
    monkeypatch.setattr(okki_client.httpx, 'get', lambda *a, **kw: httpx.Response(status, json=body))
    with pytest.raises(okki_client.OkkiApiError):
        okki_client.get_company_availability(db, 9001)


def test_availability_route_preserves_private_scope_and_write_permission(db, monkeypatch, seed_customers, bound_user):
    calls = []
    def remote(db, company_id):
        calls.append(company_id)
        return {'company_id': str(company_id), 'status': 'active', 'company_name': 'Alpha', 'owner_user_ids': [str(OKKI_UID)]}
    monkeypatch.setattr(okki_client, 'get_company_availability', remote)
    with _client(db, sub='5', permissions=['invoice:write']) as client:
        result = client.get('/api/invoice/customers/availability', params={'customer_id': '9001'})
        assert result.status_code == 200
        assert result.json()['data'] == {'company_id': '9001', 'status': 'active', 'company_name': 'Alpha'}
        assert client.get('/api/invoice/customers/availability', params={'customer_id': '9002'}).status_code == 404
        assert client.get('/api/invoice/customers/availability', params={'customer_id': 'not-an-id'}).status_code == 422
    assert calls == [9001]
    with _client(db, sub='5', permissions=['invoice:read']) as client:
        assert client.get('/api/invoice/customers/availability', params={'customer_id': '9001'}).status_code == 403


def test_remote_owner_change_is_not_treated_as_deleted(db, monkeypatch, seed_customers):
    monkeypatch.setattr(okki_client, 'get_company_availability', lambda *a: {
        'company_id': '9001', 'status': 'active', 'company_name': 'Alpha', 'owner_user_ids': ['99999999'],
    })
    result = customer_picker_service.check_availability(db, customer_id='9001', owner_okki_id=OKKI_UID)
    assert result['status'] == 'out_of_scope'


def test_token_refresh_is_bounded_and_still_checks_original_company(db, monkeypatch):
    refreshes, requests = [], []
    def token(db, *, force=False):
        refreshes.append(force)
        return 'new' if force else 'old'
    def get(url, *, headers, params, **kwargs):
        requests.append(params['company_id'])
        if headers['Authorization'] == 'Bearer old':
            return httpx.Response(401, json={})
        return httpx.Response(200, json={'code': 200, 'data': {'company_id': 9001, 'name': 'Alpha', 'owner': []}})
    monkeypatch.setattr(okki_client, 'ensure_access_token', token)
    monkeypatch.setattr(okki_client.httpx, 'get', get)
    assert okki_client.get_company_availability(db, 9001)['status'] == 'active'
    assert refreshes == [False, True]
    assert requests == [9001, 9001]


def test_timeout_does_not_become_missing(db, monkeypatch):
    monkeypatch.setattr(okki_client, 'ensure_access_token', lambda *a, **kw: 'test-token')
    def timeout(*a, **kw):
        raise httpx.ReadTimeout('synthetic timeout')
    monkeypatch.setattr(okki_client.httpx, 'get', timeout)
    with pytest.raises(okki_client.OkkiApiError):
        okki_client.get_company_availability(db, 9001)


def test_route_outage_is_retryable_without_modifying_mirror(db, monkeypatch, seed_customers, bound_user):
    from sqlalchemy import text
    before = list(db.execute(text('SELECT company_id,company_name FROM lsordertest.customer_info')).all())
    def unavailable(*args):
        raise okki_client.OkkiApiError('provider unavailable')
    monkeypatch.setattr(okki_client, 'get_company_availability', unavailable)
    with _client(db, sub='5', permissions=['invoice:write']) as client:
        response = client.get('/api/invoice/customers/availability', params={'customer_id': '9001'})
        assert response.status_code == 502
        assert '重试' in response.json()['detail']
    assert list(db.execute(text('SELECT company_id,company_name FROM lsordertest.customer_info')).all()) == before
