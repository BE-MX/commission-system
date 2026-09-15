"""Gateway contract tests. MySQL lock tests live in test_ai_gateway_mysql.py."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.ai import call_service
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.ai_gateway import admin_service, service
from app.ai_gateway.auth import hash_key
from app.ai_gateway.errors import GatewayError
from app.ai_gateway.models import GatewayApp, GatewayRequest
from app.ai_gateway.router import admin_router, router
from app.ai_gateway.schemas import AppCreate, AppPatch, ChatRequest
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db


def seed(db):
    owner = ArkUser(username='gateway-owner', password_hash='test-only', real_name='Owner')
    provider = AiProvider(name='Gateway mock', provider_type='direct', api_base='https://mock.invalid', api_type='openai')
    db.add_all([owner, provider])
    db.flush()
    preset = AiPreset(preset_name='sales_copy', provider_id=provider.id, model='mock-text',
                      system_prompt='PRIVATE SYSTEM INSTRUCTION', parameters={'max_tokens': 1024})
    db.add(preset)
    db.flush()
    owner_id, preset_id = owner.id, preset.id
    db.commit()
    app = admin_service.create_app(db, AppCreate(name='Sales site', owner_user_id=owner_id, preset_ids=[preset_id]), owner_id)
    return app, owner_id, preset_id


@pytest.fixture
def site(db):
    return seed(db)


def payload(**changes):
    return ChatRequest.model_validate({'preset': 'sales_copy', 'messages': [{'role': 'user', 'content': 'PRIVATE CUSTOMER TEXT'}], **changes})


@pytest.fixture
def upstream(monkeypatch):
    calls = []
    def fake(url, **kwargs):
        calls.append(kwargs)
        return {'choices': [{'message': {'content': 'PRIVATE ANSWER'}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}}
    monkeypatch.setattr(call_service, 'post_json', fake)
    return calls


def invoke(db, site, request_id=None):
    return service.invoke(db, hash_key(site[0]['api_key']), request_id or str(uuid4()), payload())


def test_success_uses_facade_caps_and_metadata(db, site, upstream):
    result = invoke(db, site)
    assert result['content'] == 'PRIVATE ANSWER'
    assert result['usage'] == {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30, 'status': 'known'}
    assert upstream[0]['body']['max_tokens'] == 1024
    assert upstream[0]['enforce_total_timeout'] is True
    request = db.query(GatewayRequest).one()
    log = db.get(AiCallLog, request.ai_log_id)
    assert request.status == 'success'
    assert log.caller_module == f'ai_gateway:{site[0]["id"]}'
    assert log.caller_user_id == site[1]
    assert 'PRIVATE' not in log.prompt_snapshot + log.response_snapshot


@pytest.mark.parametrize('change,status,error', [
    ({'is_enabled': False}, 403, 'app_disabled'),
    ({'daily_limit': 1}, 429, 'daily_limit_exceeded'),
    ({'rpm_limit': 1}, 429, 'rate_limit_exceeded'),
])
def test_limits_and_disabled_do_not_call_upstream(db, site, upstream, change, status, error):
    if status == 429:
        invoke(db, site)
    admin_service.update_app(db, site[0]['id'], AppPatch(**change), site[1])
    count = len(upstream)
    with pytest.raises(GatewayError) as exc:
        invoke(db, site)
    assert (exc.value.status, exc.value.error) == (status, error)
    assert len(upstream) == count


def test_duplicate_and_rotation(db, site, upstream):
    request_id = str(uuid4())
    invoke(db, site, request_id)
    with pytest.raises(GatewayError, match='') as exc:
        invoke(db, site, request_id)
    assert exc.value.status == 409 and len(upstream) == 1
    admin_service.rotate_key(db, site[0]['id'], site[1])
    with pytest.raises(GatewayError) as exc:
        invoke(db, site)
    assert exc.value.status == 401 and len(upstream) == 1


def test_owner_and_grants_checked_each_time(db, site, upstream):
    owner = db.get(ArkUser, site[1])
    owner.is_active = False
    db.commit()
    with pytest.raises(GatewayError) as exc:
        invoke(db, site)
    assert exc.value.error == 'app_disabled' and not upstream
    owner.is_active = True
    db.commit()
    with pytest.raises(GatewayError) as exc:
        service.invoke(db, hash_key(site[0]['api_key']), str(uuid4()), payload(preset='secret_preset'))
    assert exc.value.error == 'preset_not_allowed' and not upstream


def test_snapshot_survives_preset_edit(db, site, upstream):
    admission = service.admit(db, hash_key(site[0]['api_key']), str(uuid4()), payload())
    preset = db.get(AiPreset, site[2])
    preset.parameters = {'max_tokens': 99999, 'tools': [{'type': 'web_search'}]}
    preset.model = 'changed-model'
    db.commit()
    call_service.chat(db, 'sales_copy', [{'role': 'user', 'content': 'text'}], 'test',
                      snapshot_mode='metadata', trusted_text_snapshot=admission.snapshot)
    assert upstream[0]['body']['model'] == 'mock-text'
    assert upstream[0]['body']['max_tokens'] == 1024
    assert 'tools' not in upstream[0]['body']
    with pytest.raises(GatewayError) as exc:
        invoke(db, site)
    assert exc.value.error == 'preset_unavailable'


def test_unknown_timeout_keeps_slot_until_audited_resolution(db, site, monkeypatch, capsys):
    admin_service.update_app(db, site[0]['id'], AppPatch(concurrency_limit=1), site[1])
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout('PRIVATE RESPONSE AND SECRET')
    monkeypatch.setattr(call_service, 'post_json', timeout)
    with pytest.raises(GatewayError) as exc:
        invoke(db, site)
    assert exc.value.status == 504
    row = db.query(GatewayRequest).one()
    assert row.status == 'unknown' and row.tokens_used is None
    with pytest.raises(GatewayError) as exc:
        invoke(db, site)
    assert exc.value.error == 'concurrency_limit_exceeded'
    with pytest.raises(GatewayError):
        admin_service.resolve_request(db, row.app_id, row.request_id, 'Confirmed stopped upstream', site[1])
    db.rollback()
    row.created_at -= timedelta(seconds=80)
    db.commit()
    admin_service.resolve_request(db, row.app_id, row.request_id, 'Confirmed stopped upstream', site[1])
    db.refresh(row)
    assert row.status == 'timeout' and row.resolved_by == site[1]
    assert db.query(GatewayRequest).count() == 1
    assert 'PRIVATE' not in capsys.readouterr().out


@pytest.mark.parametrize('values,expected', [({}, 'unknown'), ({'tokens_prompt': 0}, 'partial'),
    ({'tokens_prompt': 0, 'tokens_completion': 0}, 'known'), ({'tokens_used': -1}, 'unknown')])
def test_unknown_usage_is_not_zero(values, expected):
    result = service.usage_fields(values)
    assert result['usage_status'] == expected
    if expected == 'unknown':
        assert result['tokens_used'] is None


@pytest.mark.parametrize('api_type', ['openai', 'anthropic'])
@pytest.mark.parametrize('raw_usage', [None, {}, [], {'input_tokens': 5}, {'input_tokens': -1, 'output_tokens': 10}, {'prompt_tokens': 'bad', 'completion_tokens': -1}])
def test_success_with_incomplete_usage(db, site, monkeypatch, api_type, raw_usage):
    db.query(AiProvider).update({'api_type': api_type})
    db.commit()
    def fake(*args, **kwargs):
        result = {'choices': [{'message': {'content': 'answer'}}]} if api_type == 'openai' else {'content': [{'type': 'text', 'text': 'answer'}]}
        return {**result, 'usage': raw_usage}
    monkeypatch.setattr(call_service, 'post_json', fake)
    result = invoke(db, site)
    assert result['content'] == 'answer'
    assert result['usage']['total_tokens'] is None
    assert db.query(GatewayRequest).one().status == 'success'
    log = db.query(AiCallLog).one()
    assert log.status == 'success' and log.tokens_used is None


def test_persistence_failure_never_returns_success_or_retries(db, site, upstream, monkeypatch):
    from sqlalchemy.exc import OperationalError
    real_finish = service.finish
    def fail_finish(*args, **kwargs):
        raise OperationalError('write failed', None, None)
    monkeypatch.setattr(service, 'finish', fail_finish)
    with pytest.raises(OperationalError):
        invoke(db, site)
    assert len(upstream) == 1 and db.query(GatewayRequest).one().status == 'pending'


def test_http_failure_retains_count_but_releases_slot(db, site, monkeypatch):
    def failure(*args, **kwargs):
        request = httpx.Request('POST', 'https://mock.invalid')
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError('PRIVATE UPSTREAM', request=request, response=response)
    monkeypatch.setattr(call_service, 'post_json', failure)
    with pytest.raises(GatewayError) as exc:
        invoke(db, site)
    assert exc.value.status == 502
    row = db.query(GatewayRequest).one()
    assert row.status == 'error' and row.tokens_used is None
    summary = admin_service.list_apps(db, 1, 20)['items'][0]
    assert summary['today_calls'] == 1 and summary['occupied'] == 0


@pytest.mark.parametrize('change', [
    {'messages': [{'role': 'system', 'content': 'x'}]},
    {'messages': [{'role': 'user', 'content': [{'type': 'image_url'}]}]},
    {'messages': [{'role': 'user', 'content': 'x' * 16001}]},
    {'messages': [{'role': 'assistant', 'content': 'x'}]},
    {'model': 'expensive'}, {'caller_user_id': 1}, {'max_tokens': 99999},
])
def test_strict_payload(change):
    with pytest.raises(ValidationError):
        payload(**change)


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router, prefix='/api/ai-gateway')
    app.include_router(admin_router, prefix='/api/ai-gateway/admin')
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client


def test_http_contract_and_admin_denial(client, site, upstream):
    headers = {'Authorization': f'Bearer {site[0]["api_key"]}', 'X-Request-ID': str(uuid4())}
    url = '/api/ai-gateway/chat'
    response = client.post(url, headers=headers, json=payload().model_dump())
    assert response.status_code == 200 and response.json()['code'] == 0
    assert response.headers['cache-control'] == 'no-store'
    assert client.post(url, headers=headers, json=payload().model_dump()).status_code == 409
    assert client.post(url, json=payload().model_dump()).status_code == 401
    assert client.get('/api/ai-gateway/admin/apps', headers=headers).status_code in (401, 403)
    client.app.dependency_overrides[get_current_user] = lambda: {'sub': str(site[1]), 'permissions': [], 'roles': []}
    assert client.get('/api/ai-gateway/admin/apps').status_code == 403
    client.app.dependency_overrides[get_current_user] = lambda: {'sub': str(site[1]), 'permissions': ['ai:admin'], 'roles': []}
    listing = client.get('/api/ai-gateway/admin/apps')
    assert listing.status_code == 200
    assert 'api_key' not in listing.text and 'key_hash' not in listing.text
    assert site[0]['api_key'] not in listing.text


def test_size_and_validation_errors_never_echo_content(client, site, upstream):
    headers = {'Authorization': f'Bearer {site[0]["api_key"]}', 'X-Request-ID': str(uuid4()), 'Content-Type': 'application/json'}
    response = client.post('/api/ai-gateway/chat', headers=headers, content='x' * 65537)
    assert response.status_code == 413
    response = client.post('/api/ai-gateway/chat', headers=headers, json={'PRIVATE': 'secret'})
    assert response.status_code == 422 and 'PRIVATE' not in response.text
    assert response.json()['data']['request_id'] == headers['X-Request-ID']
    assert not upstream


def test_beijing_day_changes_independent_of_server_timezone(db, site, upstream, monkeypatch):
    import app.core.time as time_module
    class ServerUtcClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 9, 11, 15, 59, 59, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(time_module, 'datetime', ServerUtcClock)
    first = time_module.beijing_now()
    assert first == datetime(2026, 9, 11, 23, 59, 59)
    monkeypatch.setattr(service, 'beijing_now', lambda: first)
    admin_service.update_app(db, site[0]['id'], AppPatch(daily_limit=1, rpm_limit=1), site[1])
    invoke(db, site)
    with pytest.raises(GatewayError):
        invoke(db, site)
    midnight = first + timedelta(seconds=1)
    monkeypatch.setattr(service, 'beijing_now', lambda: midnight)
    invoke(db, site)
    assert len(upstream) == 2
    assert service.day_window(midnight)[0] == midnight
