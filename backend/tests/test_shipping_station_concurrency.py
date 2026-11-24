"""Worker isolation regression: slow station operations must leave the loop usable."""
import asyncio
from io import BytesIO
import threading
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import UploadFile, Headers
from app.shipping_inspection import station_router, station_service, file_service


@pytest.mark.asyncio
async def test_station_sync_operation_does_not_block_loop():
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    def slow(db):
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(3)
        return {'done': True}
    task = asyncio.create_task(station_router.invoke(None, slow))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert not task.done()
    finally:
        release.set()
    assert (await task)['data'] == {'done': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['photos', 'videos'])
async def test_preflight_responds_while_station_upload_waits_for_db(monkeypatch, endpoint):
    app = FastAPI()
    app.include_router(station_router.router)
    app.add_middleware(CORSMiddleware, allow_origins=["https://office.test"], allow_methods=["GET"])
    app.dependency_overrides[station_router.login_id] = lambda: 1
    app.dependency_overrides[station_router.get_db] = lambda: Mock()
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def wait_for_session(db, login_id, session_id):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(3)
        raise station_service.StationError('STALE', 'refresh', 409)

    monkeypatch.setattr(station_service, 'session_for', wait_for_session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        task = asyncio.create_task(client.post(
            f'/station/sessions/active/{endpoint}', files={'file': ('sample', b'bytes')},
            data={'edit_version': '0', 'request_id': 'request'},
        ))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            probe = await client.options('/station/operators', headers={
                'Origin': 'https://office.test', 'Access-Control-Request-Method': 'GET',
            })
            assert probe.status_code == 200
            assert not task.done()
        finally:
            release.set()
            response = await task
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'STALE'


@pytest.mark.asyncio
async def test_video_spool_storage_keeps_async_facade_and_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(file_service, 'storage_root', lambda: tmp_path)
    data = b'\0\0\0\x18ftypisom' + b'x' * (1024 * 1024)
    upload = UploadFile(BytesIO(data), filename='clip.mp4', headers=Headers({'content-type': 'video/mp4'}))
    path = await file_service.store_video(upload)
    assert file_service.resolve_path(path).read_bytes() == data
    assert not list(tmp_path.rglob('*.part'))

@pytest.mark.asyncio
async def test_station_error_rollback_runs_off_loop():
    from fastapi import HTTPException
    loop_thread = threading.get_ident()
    rolled_back = []
    class DB:
        def rollback(self):
            assert threading.get_ident() != loop_thread
            rolled_back.append(True)
    def rejected(db):
        raise station_service.StationError('STALE', 'refresh', 409)
    with pytest.raises(HTTPException) as exc:
        await station_router.invoke(DB(), rejected)
    assert exc.value.status_code == 409
    assert rolled_back == [True]
