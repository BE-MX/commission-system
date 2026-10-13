from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.whatsapp import router, assistant_router, assistant_service as service
from tests.test_whatsapp_assistant import scope, account, output


@pytest.fixture
def api(db, scope, monkeypatch):
    app = FastAPI(); app.include_router(router.router, prefix='/api/whatsapp')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {'sub': str(scope.ark_user_id), 'roles': [], 'permissions': ['whatsapp:read']}
    monkeypatch.setattr(assistant_router, 'run_background', lambda uid: service.execute_run(db, uid, chat_fn=output))
    with TestClient(app) as client:
        yield client


def body(scope):
    return {'account_uid': scope.account_uid, 'start_at': '2026-10-12T16:00:00Z',
        'end_at': '2026-10-13T00:01:00+08:00', 'client_request_uid': 'api-request'}


def test_api_background_completion_readback_and_internal_checklist(api, scope):
    prefix = '/api/whatsapp/ai-assistant'
    options = api.get(prefix + '/options', params={'account_uid': scope.account_uid})
    assert options.json()['data']['can_analyze']
    admitted = api.post(prefix + '/runs', json=body(scope))
    assert admitted.status_code == 200 and admitted.json()['data']['status'] == 'pending'
    uid = admitted.json()['data']['run_uid']
    result = api.get(prefix + '/runs/' + uid).json()['data']
    assert result['status'] == 'succeeded' and result['message_count'] == 2
    ref = result['results'][0]['tasks'][0]['task_uid']
    changed = api.patch(f'{prefix}/runs/{uid}/tasks/{ref}', json={'completed': True})
    assert changed.status_code == 200 and changed.json()['data']['results'][0]['tasks'][0]['completed']
    assert api.post(prefix + '/runs', json=body(scope)).json()['data']['run_uid'] == uid
    readback = api.get(prefix + '/runs/requests/api-request', params={'account_uid': scope.account_uid})
    assert readback.json()['data']['run_uid'] == uid
    recent = api.get(prefix + '/runs', params={'account_uid': scope.account_uid}).json()['data']['items']
    assert len(recent) == 1 and recent[0]['results'] == []
    assert api.get(prefix + '/runs/requests/unknown', params={'account_uid': scope.account_uid}).status_code == 404


def test_api_offset_required_and_egress_denied_without_any_model(api, scope):
    prefix = '/api/whatsapp/ai-assistant'
    data = body(scope); data['start_at'] = '2026-10-13T00:00:00'
    assert api.post(prefix + '/runs', json=data).status_code == 422
    scope.ai_egress_allowed = False
    assert api.post(prefix + '/runs', json=body(scope)).status_code == 403
