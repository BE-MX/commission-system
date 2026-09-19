import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.config import get_settings
from app.core.storage.cos import ObjectMissing, StorageError
from app.core.storage.models import StorageAlias, StorageTransfer
from app.colorwork import storage_service as service
from app.colorwork.storage_router import router


@pytest.fixture(autouse=True)
def cloud_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['colorwork'])
    monkeypatch.setattr(get_settings(), 'COS_CACHE_ROOT', str(tmp_path/'cache'))


class Store:
    def __init__(self):
        self.data = {}
    def head(self, key):
        if key not in self.data:
            raise ObjectMissing('missing')
        body, metadata = self.data[key]
        return {'Content-Length': str(len(body)), 'Content-Type': 'image/png', 'ETag':hashlib.md5(body).hexdigest(),
                'x-cos-meta-sha256':hashlib.sha256(body).hexdigest(), **{'x-cos-meta-'+k:v for k,v in metadata.items()}}
    def put_file(self, key, path, content_type, *, custom_metadata=None):
        self.data[key] = (Path(path).read_bytes(), custom_metadata or {})


def test_failed_upload_does_not_replace_existing_alias(db, tmp_path):
    store = Store();path = tmp_path/'file';path.write_bytes(b'first')
    service.publish(db, 'test.jpg', path, 'image/jpeg', {}, False, store)
    old = service.target(db, 'test.jpg')
    def fail(*args, **kwargs):
        raise StorageError('offline')
    store.put_file = fail
    with pytest.raises(StorageError):
        service.publish(db, 'test.jpg', path, 'image/jpeg', {}, False, store)
    assert service.target(db, 'test.jpg') == old


def test_if_none_match_preserves_migrated_object_then_delete_tombstones(db, tmp_path):
    store=Store();store.data['old.jpg']=(b'old', {})
    path=tmp_path/'file';path.write_bytes(b'new')
    with pytest.raises(HTTPException) as exc:
        service.publish(db,'old.jpg',path,'image/jpeg',{},True,store)
    assert exc.value.status_code==412
    assert service.target(db,'old.jpg')=='old.jpg'
    service.delete(db,'old.jpg')
    assert service.target(db,'old.jpg') is None
    assert db.get(StorageTransfer,service.identity('old.jpg')).status=='deleted'
    assert service.head(db,'old.jpg',store)==(None,None)


def test_gateway_rejects_browser_and_missing_credentials(db, monkeypatch):
    monkeypatch.setattr(get_settings(),'COS_ENABLED_DOMAINS',['colorwork'])
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_db]=lambda:db
    with TestClient(app,client=('127.0.0.1',1)) as client:
        assert client.get('/storage/metadata?key=a').status_code==403
        assert client.put('/storage/object?key=a',headers={'x-ark-storage-key':service.secret(),'content-length':'999999999'},content=b'').status_code==413
        assert client.get('/storage/metadata?key=../x',headers={'x-ark-storage-key':service.secret()}).status_code==400
    with TestClient(app,client=('203.0.113.1',1)) as client:
        assert client.get('/storage/metadata?key=a',headers={'x-ark-storage-key':service.secret()}).status_code==403


@pytest.mark.parametrize('intervening', ['delete', 'replace'])
def test_lost_completion_response_cannot_resurrect_or_overwrite(db, tmp_path, intervening):
    store=Store();path=tmp_path/'file';path.write_bytes(b'first')
    first=service.publish(db,'result.psd',path,'application/octet-stream',{},False,store,operation_id='a'*64)
    if intervening=='delete':
        service.delete(db,'result.psd')
    else:
        path.write_bytes(b'newer')
        service.publish(db,'result.psd',path,'application/octet-stream',{},False,store,operation_id='b'*64)
    current=service.target(db,'result.psd')
    count=len(store.data)
    replay=service.publish(db,'result.psd',path,'application/octet-stream',{},False,store,operation_id='a'*64)
    assert replay==first
    assert service.target(db,'result.psd')==current
    assert len(store.data)==count



def test_gateway_accepts_bounded_chunked_worker_upload_and_streams_range(db, monkeypatch):
    import io
    from types import SimpleNamespace
    from app.colorwork import storage_router
    store=Store()
    store.key=lambda key:key
    def call(method, **kwargs):
        assert method=='get_object'
        data=store.data[kwargs['Key']][0]
        if 'Range' in kwargs:
            start,end=map(int,kwargs['Range'].removeprefix('bytes=').split('-'))
            data=data[start:end+1]
        return {'Body':SimpleNamespace(get_raw_stream=lambda:io.BytesIO(data))}
    store._call=call
    monkeypatch.setattr(service,'CosObjectStore',lambda domain:store)
    monkeypatch.setattr(storage_router,'CosObjectStore',lambda domain:store)
    app=FastAPI();app.include_router(router);app.dependency_overrides[get_db]=lambda:db
    headers={'x-ark-storage-key':service.secret(),'x-ark-content-length':'8','content-type':'image/png'}
    with TestClient(app,client=('127.0.0.1',1)) as client:
        response=client.put('/storage/object?key=image.png',content=iter([b'1234',b'5678']),headers=headers)
        assert response.status_code==200,response.text
        assert response.json()['customMetadata']['sha256']==hashlib.sha256(b'12345678').hexdigest()
        response=client.get('/storage/object?key=image.png&offset=2&length=3',headers=headers)
        assert response.status_code==200
        assert response.content==b'345'
        assert response.headers['content-length']=='3'
        assert client.put('/storage/object?key=bad',content=b'too long!',headers=headers).status_code==413
        assert service.target(db,'bad')=='bad'
