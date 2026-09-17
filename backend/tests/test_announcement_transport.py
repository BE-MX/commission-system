"""Mocked wire contracts; never calls DingTalk."""
import asyncio
import json
from types import SimpleNamespace
import pytest
import httpx
from app.dingtalk import announcement_sender as sender


@pytest.mark.parametrize('status,body,uncertain,retryable', [
    (200, {'processQueryKey': 'receipt'}, False, False),
    (200, {}, True, False), (429, {}, False, True),
    (500, {}, True, False), (403, {}, False, False),
])
def test_group_message_contract(monkeypatch, status, body, uncertain, retryable):
    captured = {}
    class Http:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            captured.update(url=url, **kwargs)
            return httpx.Response(status, json=body)
    monkeypatch.setattr(sender.httpx, 'AsyncClient', Http)
    call = sender.send_prepared('token', 'group', 'robot', 'sampleImageMsg', {'photoURL': 'private-media-id'})
    if body.get('processQueryKey'):
        assert asyncio.run(call) == 'receipt'
    else:
        with pytest.raises(sender.AnnouncementSendError) as error:
            asyncio.run(call)
        assert error.value.uncertain == uncertain
        assert error.value.retryable == retryable
    assert captured['json']['openConversationId'] == 'group'
    assert captured['json']['robotCode'] == 'robot'
    assert captured['json']['msgKey'] == 'sampleImageMsg'
    assert json.loads(captured['json']['msgParam']) == {'photoURL': 'private-media-id'}
    assert captured['headers'] == {'x-acs-dingtalk-access-token': 'token'}


def test_image_upload_uses_private_file_and_returns_media_id(monkeypatch, tmp_path):
    path = tmp_path / 'image.png'
    path.write_bytes(b'test-image')
    class Client:
        app_key, app_secret = 'key', 'secret'
        async def get_access_token(self): return 'token'
    class Http:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            assert kwargs['params']['type'] == 'image'
            assert kwargs['files']['media'][1].read() == b'test-image'
            return httpx.Response(200, json={'errcode': 0, 'media_id': 'media-id'})
    monkeypatch.setattr(sender, 'DingTalkClient', Client)
    monkeypatch.setattr(sender.httpx, 'AsyncClient', Http)
    monkeypatch.setattr(sender, 'resolve_private_path', lambda _: path)
    db = SimpleNamespace(get=lambda *_: SimpleNamespace(deleted_at=None, storage_path='private', mime_type='image/png'))
    assert asyncio.run(sender.prepare(db, {'kind': 'image', 'asset_id': 1})) == ('token', 'sampleImageMsg', {'photoURL': 'media-id'})
