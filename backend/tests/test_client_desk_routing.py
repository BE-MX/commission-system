"""Exercise the production router registration boundary and request DTOs."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.routers import register_routers


@pytest.fixture
def api():
    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = lambda: None
    return app, TestClient(app)


def test_registered_desk_routes_use_single_prefix_and_read_permission(api, monkeypatch):
    from app.client_desk import service
    app, client = api
    app.dependency_overrides[get_current_user] = lambda: {'sub':'1','roles':[],'permissions':['customer:read']}
    assert client.get('/api/client-desk/today').status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {'sub':'1','roles':[],'permissions':['client_desk:read']}
    monkeypatch.setattr(service, 'today', lambda db, user, reason: {'requested_reason':reason})
    response = client.get('/api/client-desk/today?reason=R1_UNREPLIED')
    assert response.status_code == 200
    assert response.json()['data']['requested_reason'] == 'R1_UNREPLIED'


def test_public_report_preview_does_not_require_or_consume_ticket(api):
    _, client = api
    for _ in range(2):
        result = client.get('/api/client-desk/reports/handoff?ticket=untrusted-preview')
        assert result.status_code == 200
        assert result.json()['data'] == {'action':'continue','login_required':True}
        assert result.headers['cache-control'] == 'no-store'


def test_feedback_date_and_write_permission_are_enforced(api, monkeypatch):
    from app.client_desk import service
    app, client = api
    app.dependency_overrides[get_current_user] = lambda: {'sub':'1','roles':[],'permissions':['client_desk:read']}
    assert client.post('/api/client-desk/suggestions/5/feedback',json={'value':'done'}).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {'sub':'1','roles':[],'permissions':['client_desk:write']}
    monkeypatch.setattr(service, 'feedback', lambda db, user, sid, payload: {'date':payload.date})
    result = client.post('/api/client-desk/suggestions/5/feedback',json={'value':'snoozed','date':'2026-11-12'})
    assert result.status_code == 200
    assert result.json()['data']['date'] == '2026-11-12'


def test_copy_draft_requests_explicit_fresh_ownership(api, monkeypatch):
    from app.client_desk import service
    app, client = api
    app.dependency_overrides[get_current_user] = lambda: {'sub': '1', 'roles': [], 'permissions': ['client_desk:read']}
    monkeypatch.setattr(service, 'detail', lambda *a: {'fresh': False})
    monkeypatch.setattr(service, 'fresh_detail', lambda *a: {'fresh': True})
    assert client.get('/api/client-desk/customers/801').json()['data']['fresh'] is False
    assert client.get('/api/client-desk/customers/801?fresh=true').json()['data']['fresh'] is True
