"""Customer media upload must yield the ASGI loop during synchronous work."""
import asyncio
import threading
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import UploadFile

from app.customer_media import router, service, storage


def _upload():
    content = BytesIO()
    Image.new('RGB', (2, 3)).save(content, format='PNG')
    content.seek(0)
    return UploadFile(content, filename='example.png')


async def _probe(operation, entered, release):
    task = asyncio.create_task(operation)
    try:
        async def wait_for_worker():
            while not entered.is_set():
                await asyncio.sleep(0.001)
        await asyncio.wait_for(wait_for_worker(), timeout=2)
        assert not task.done()
    finally:
        release.set()
    return await task


def test_local_fsync_yields_loop(tmp_path, monkeypatch):
    local = storage.LocalMediaStorage(tmp_path)
    entered, release = threading.Event(), threading.Event()
    main = threading.get_ident()
    def fsync(_fd):
        assert threading.get_ident() != main
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(storage.os, 'fsync', fsync)
    result = asyncio.run(_probe(local.save_upload(
        _upload(), customer_id='C1', batch_id=1, max_bytes=1024,
    ), entered, release))
    assert (result.width, result.height) == (2, 3)
    assert local.resolve(result.object_key).is_file()


@pytest.mark.parametrize('failure', [False, True])
def test_upload_sql_response_and_cleanup_off_loop(monkeypatch, failure):
    main = threading.get_ident()
    calls, row, stored = [], object(), object()
    def check(name):
        assert threading.get_ident() != main, name
        calls.append(name)
    def prepare(*args):
        check('prepare')
        return 1, 'C1', 4096, 1024
    async def save(*args, **kwargs):
        calls.append('store')
        return stored
    def factory():
        check('storage_for')
        return SimpleNamespace(save_upload=save)
    def finish(*args):
        check('finish')
        if failure:
            raise service.CustomerMediaConflict('batch changed')
        return row
    def rollback(db, value):
        check('rollback_cleanup')
        assert value is stored
    def full(db, value):
        check('response_sql')
        assert value is row
        return {'id': 1}
    monkeypatch.setattr(service, '_prepare_upload', prepare)
    monkeypatch.setattr(service, 'storage_for', factory)
    monkeypatch.setattr(service, '_finish_upload', finish)
    monkeypatch.setattr(service, '_rollback_upload', rollback)
    monkeypatch.setattr(router, '_batch_full', full)
    operation = router.upload_batch_asset(1, file=_upload(), directory_id=None,
        directory_name=None, tags_json=None, db=object(), payload={})
    if failure:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(operation)
        assert exc.value.status_code == 409
        assert calls[-1] == 'rollback_cleanup'
    else:
        assert asyncio.run(operation)['data'] == {'id': 1}
        assert calls == ['prepare', 'storage_for', 'store', 'finish', 'response_sql']


def test_cos_cleanup_and_temp_removal_yield_loop(tmp_path, monkeypatch):
    main = threading.get_ident()
    monkeypatch.setattr(storage, 'get_settings', lambda: SimpleNamespace(COS_CACHE_ROOT=str(tmp_path)))
    entered, release, deleted = threading.Event(), threading.Event(), []
    class Store:
        def put_file(self, *args):
            assert threading.get_ident() != main
            raise storage.StorageError('unavailable')
        def delete(self, key):
            assert threading.get_ident() != main
            entered.set()
            assert release.wait(3)
            deleted.append(key)
    with pytest.raises(storage.StorageError):
        asyncio.run(_probe(storage.CosMediaStorage(Store()).save_upload(
            _upload(), customer_id='C1', batch_id=1, max_bytes=1024,
        ), entered, release))
    assert len(deleted) == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("directory_mode", ["name", "id"])
def test_real_upload_queries_and_response_enrichment_off_loop(db, tmp_path, monkeypatch, directory_mode):
    import json
    from sqlalchemy import event
    from tests.test_customer_media import _add_customer, _payload, _sample_tags, _seed_workflow

    _add_customer(db, 'CUST-MEDIA-1', 'Media customer')
    _, designer, _, task = _seed_workflow(db)
    writer = _payload(designer, 'customer_media:write')
    batch_id = service.get_or_create_batch(db, task.id, writer).id
    tags = _sample_tags(db)
    directory_id = (service.create_directory(db, batch_id, writer, 'Photos')['id']
                    if directory_mode == 'id' else None)
    local = storage.LocalMediaStorage(tmp_path)
    monkeypatch.setattr(service, 'storage_for', lambda provider=None: local)
    main = threading.get_ident()
    statements, directory_locks, rollbacks = [], [], []

    def after_rollback(_session):
        rollbacks.append(True)

    def check_directory_lock(state):
        from app.customer_media.models import CustomerMediaDirectory
        statement = state.statement
        if not state.is_select or getattr(statement, '_for_update_arg', None) is None:
            return
        if any(d.get('entity') is CustomerMediaDirectory for d in statement.column_descriptions):
            assert len(rollbacks) >= (2 if directory_mode == 'name' else 1)
            directory_locks.append(True)

    def check_sql(_conn, _cursor, statement, _params, _context, _many):
        assert threading.get_ident() != main
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', check_sql)
    event.listen(db, 'after_rollback', after_rollback)
    event.listen(db, 'do_orm_execute', check_directory_lock)
    try:
        response = asyncio.run(router.upload_batch_asset(
            batch_id, file=_upload(), directory_id=directory_id,
            directory_name='Photos' if directory_mode == 'name' else None,
            tags_json=json.dumps(tags), db=db, payload=writer,
        ))
    finally:
        event.remove(engine, 'before_cursor_execute', check_sql)
        event.remove(db, 'after_rollback', after_rollback)
        event.remove(db, 'do_orm_execute', check_directory_lock)
    assert len(directory_locks) == 1
    assert statements
    assert response['data']['assets'][0]['tags']
    assert response['data']['directories'][0]['asset_count'] == 1


def test_cancelled_upload_waits_for_finalization_before_session_can_close(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    finalized = []
    monkeypatch.setattr(service, '_prepare_upload', lambda *args: (1, 'C1', 4096, 1024))
    async def save(*args, **kwargs):
        await asyncio.sleep(0)
        return object()
    monkeypatch.setattr(service, 'storage_for', lambda: SimpleNamespace(save_upload=save))
    def finish(*args):
        entered.set()
        assert release.wait(3)
        finalized.append(True)
        return object()
    monkeypatch.setattr(service, '_finish_upload', finish)
    async def scenario():
        task = asyncio.create_task(service.upload_asset(object(), 1, {}, _upload()))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finalized == [True]
    asyncio.run(scenario())


def test_upload_capacity_rejects_overflow_and_cleans_new_file(db, tmp_path, monkeypatch):
    from tests.test_customer_media import _add_customer, _payload, _sample_tags, _seed_workflow

    _add_customer(db, 'CUST-MEDIA-1', 'Media customer')
    _, designer, _, task = _seed_workflow(db)
    writer = _payload(designer, 'customer_media:write')
    batch_id = service.get_or_create_batch(db, task.id, writer).id
    tags = _sample_tags(db)
    local = storage.LocalMediaStorage(tmp_path)
    monkeypatch.setattr(service, 'storage_for', lambda provider=None: local)
    first = asyncio.run(service.upload_asset(db, batch_id, writer, _upload(), tags=tags))
    size = first.assets[0].file_size
    original = service._prepare_upload
    def limited(*args):
        user_id, customer_id, _, max_file = original(*args)
        return user_id, customer_id, size, max_file
    monkeypatch.setattr(service, '_prepare_upload', limited)
    with pytest.raises(service.CustomerMediaConflict, match='容量上限'):
        asyncio.run(service.upload_asset(db, batch_id, writer, _upload(), tags=tags))
    assert len(service.get_batch(db, batch_id).assets) == 1
    assert len(list(tmp_path.rglob('*.png'))) == 1
