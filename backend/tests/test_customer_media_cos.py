"""Private media provider behavior, independent of real cloud and database."""
import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from starlette.datastructures import UploadFile

from app.core.storage.cos import ObjectMissing, StorageError, StoredObject
from app.customer_media import storage


def test_verified_upload_publishes_cos_provider_and_cleans_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'get_settings', lambda: SimpleNamespace(COS_CACHE_ROOT=str(tmp_path)))
    captured = []
    class Store:
        def put_file(self, key, path, content_type):
            from app.core.storage.cos import file_digest
            size, digest = file_digest(path)
            captured.append((key, path, content_type))
            return StoredObject(key, size, digest, content_type)
    content = BytesIO()
    Image.new('RGB', (2, 3)).save(content, format='PNG')
    content.seek(0)
    result = asyncio.run(storage.CosMediaStorage(Store()).save_upload(
        UploadFile(content, filename='example.png'), customer_id='C1', batch_id=2, max_bytes=1024))
    assert result.provider == 'cos'
    assert (result.width, result.height) == (2, 3)
    assert not captured[0][1].exists()
    assert not list(tmp_path.iterdir())


def test_failed_cloud_upload_is_not_reported_as_local_success(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'get_settings', lambda: SimpleNamespace(COS_CACHE_ROOT=str(tmp_path)))
    class Store:
        def put_file(self, *args):
            raise StorageError('unavailable')
    data = BytesIO()
    Image.new('RGB', (1, 1)).save(data, format='PNG')
    data.seek(0)
    with pytest.raises(StorageError):
        asyncio.run(storage.CosMediaStorage(Store()).save_upload(
            UploadFile(data, filename='example.png'), customer_id='C1', batch_id=2, max_bytes=1024))
    assert not list(tmp_path.iterdir())


def test_missing_cos_object_never_falls_back_to_local_file():
    from fastapi import HTTPException
    class Store:
        def head(self, key):
            raise ObjectMissing('missing')
    asset = SimpleNamespace(object_key='known/object')
    with pytest.raises(HTTPException) as raised:
        storage.CosMediaStorage(Store()).response(asset)
    assert raised.value.status_code == 404


def test_cloud_media_redirect_is_private_and_does_not_forward_credentials():
    class Store:
        def head(self, key):
            return {}
        def download_url(self, key, **kwargs):
            assert kwargs['download'] is False
            return 'https://example.invalid/object?signature=test'
    asset = SimpleNamespace(object_key='key', file_name='photo.jpg', content_type='image/jpeg')
    response = storage.CosMediaStorage(Store()).response(asset)
    assert response.status_code == 303
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert 'authorization' not in response.headers


def test_cloud_outage_is_retryable_not_reported_as_missing():
    from fastapi import HTTPException
    class Store:
        def head(self, key):
            raise StorageError('temporary failure')
    with pytest.raises(HTTPException) as raised:
        storage.CosMediaStorage(Store()).response(SimpleNamespace(object_key='key'))
    assert raised.value.status_code == 503
    assert raised.value.headers['Retry-After'] == '10'


@pytest.mark.parametrize('referenced', [True, 'unavailable'])
def test_uncertain_commit_preserves_original(monkeypatch, referenced):
    from app.customer_media import service
    calls = []
    class Database:
        def scalar(self, query):
            if referenced == 'unavailable':
                raise RuntimeError('connection unavailable')
            return 17
        def rollback(self):
            pass
    monkeypatch.setattr(service, 'storage_for', lambda provider: SimpleNamespace(delete=calls.append))
    service._cleanup_unbound_upload(Database(), SimpleNamespace(provider='cos', object_key='file'))
    assert not calls
