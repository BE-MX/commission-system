"""End-to-end site adapter requests against a mock gateway, no paid calls."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json

from fastapi.testclient import TestClient
import httpx


def test_example_auth_server_parameters_and_no_retries():
    path = Path(__file__).parents[2] / 'examples/ai-site-gateway/main.py'
    spec = spec_from_file_location('site_example', path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    def mock(request):
        calls.append(request)
        if len(calls) == 2:
            raise httpx.ReadTimeout('Secret upstream exception')
        return httpx.Response(200, json={'code': 0, 'data': {'content': 'Generated text'}})
    config = module.Settings(_env_file=None, ARK_AI_BASE_URL='https://mock.invalid/api/ai-gateway',
        ARK_AI_KEY='server-only-test-key', ARK_AI_PRESET='sales_copy', SITE_VISITOR_TOKEN='visitor-invitation-' + 'x' * 32)
    with TestClient(module.create_app(config, httpx.MockTransport(mock))) as client:
        assert client.post('/generate', json={'text': 'hello'}).status_code == 401
        assert not calls
        headers = {'Authorization': 'Bearer ' + config.SITE_VISITOR_TOKEN}
        response = client.post('/generate', json={'text': 'hello'}, headers=headers)
        assert response.status_code == 200
        assert 'server-only-test-key' not in response.text
        assert json.loads(calls[0].content)['preset'] == 'sales_copy'
        assert calls[0].headers['authorization'] == 'Bearer server-only-test-key'
        assert calls[0].headers['x-request-id'] == response.json()['request_id']
        response = client.post('/generate', json={'text': 'hello'}, headers=headers)
        assert response.status_code == 502 and len(calls) == 2
        assert 'Secret' not in response.text
