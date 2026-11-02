"""Batch clearing must stay atomic and scoped to the confirmed editable batch."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, update

from app.customer_media import service
from app.customer_media.models import CustomerMediaAsset, CustomerMediaBatch, CustomerMediaDirectory
from tests.test_customer_media_directory_delete import media, add_shared_batch
from tests.test_customer_media import _sample_tags, _upload_png
from tests.test_customer_media_tags import _internal_app, _payload


@pytest.mark.parametrize('batch_status', ['draft', 'changes_requested'])
def test_clear_batch_preserves_other_batches_shared_directory_and_customer_tags(db, media, batch_status):
    _, designer, _, task, writer, batch, first, storage = media
    batch_id, directory_id = batch.id, first.directory_id
    batch.status = batch_status
    db.commit()
    previous_version = batch.lock_version
    second = add_shared_batch(db, media)
    other_id, other_key = second.assets[0].id, second.assets[0].object_key
    updated = asyncio.run(service.upload_asset(db, batch_id, writer, _upload_png('loose.png'), tags=_sample_tags(db)))
    ids = [asset.id for asset in updated.assets]
    files = [asset.object_key for asset in updated.assets]
    labels = service.list_customer_tags(db, batch.customer_id)
    with TestClient(_internal_app(db, _payload(designer, 'customer_media:write'))) as client:
        response = client.request('DELETE', f'/api/customer-media/batches/{batch_id}/assets', json={'asset_ids': ids})
        assert response.status_code == 200, response.text
        assert response.json()['data']['assets'] == []
        assert response.json()['data']['lock_version'] == previous_version + 1
        assert client.get(f'/api/customer-media/tasks/{task.id}/batch').json()['data']['assets'] == []
        # A repeated request cannot delete files subsequently uploaded to this batch.
        assert client.request('DELETE', f'/api/customer-media/batches/{batch_id}/assets', json={'asset_ids': ids}).status_code == 200
    assert all(db.get(CustomerMediaAsset, asset_id).deleted_at is not None for asset_id in ids)
    assert all(not storage.resolve(key).exists() for key in files)
    assert db.get(CustomerMediaAsset, other_id).deleted_at is None
    assert storage.resolve(other_key).exists()
    assert db.get(CustomerMediaDirectory, directory_id) is not None
    assert service.list_customer_tags(db, batch.customer_id) == labels
    assert task.status == 'in_progress'
    assert service.get_batch(db, batch_id).lock_version == previous_version + 1
    with pytest.raises(service.CustomerMediaConflict, match='已被更新'):
        service.submit_batch(db, batch_id, writer, previous_version)
    assert [review.action for review in service.get_batch(db, batch_id).reviews].count('clear_assets') == 1


@pytest.mark.parametrize('status', ['pending_review', 'published', 'unpublished'])
def test_clear_batch_rejects_noneditable_status(db, media, status):
    _, _, _, _, writer, batch, asset, storage = media
    batch.status = status
    db.commit()
    with pytest.raises(service.CustomerMediaConflict, match='当前状态'):
        service.clear_batch_assets(db, batch.id, writer, [asset.id])
    assert db.get(CustomerMediaAsset, asset.id).deleted_at is None
    assert storage.resolve(asset.object_key).exists()


def test_clear_batch_rejects_unassigned_writer_and_readonly_permission(db, media):
    applicant, designer, _, _, _, batch, asset, storage = media
    for user, permission in [(applicant, 'customer_media:write'), (designer, 'customer_media:read')]:
        with TestClient(_internal_app(db, _payload(user, permission))) as client:
            response = client.request('DELETE', f'/api/customer-media/batches/{batch.id}/assets', json={'asset_ids': [asset.id]})
            assert response.status_code == 403
    assert db.get(CustomerMediaAsset, asset.id).deleted_at is None
    assert storage.resolve(asset.object_key).exists()


def test_clear_batch_rejects_changed_snapshot_and_foreign_ids(db, media):
    _, _, _, _, writer, batch, first, storage = media
    first_id, batch_id = first.id, batch.id
    second = add_shared_batch(db, media)
    updated = asyncio.run(service.upload_asset(db, batch_id, writer, _upload_png('later.png'), tags=_sample_tags(db)))
    ids = [asset.id for asset in updated.assets]
    for expected in ([first_id], ids + [second.assets[0].id]):
        with pytest.raises(service.CustomerMediaConflict, match='素材已变化'):
            service.clear_batch_assets(db, batch_id, writer, expected)
        assert all(db.get(CustomerMediaAsset, asset_id).deleted_at is None for asset_id in ids)
    assert storage.resolve(first.object_key).exists()


def test_clear_batch_refreshes_cached_status_when_lock_is_acquired(db, media):
    _, _, _, _, writer, batch, asset, storage = media
    batch_id, asset_id = batch.id, asset.id
    changed = False

    def update_status(state):
        nonlocal changed
        statement = state.statement
        if not changed and state.is_select and getattr(statement, '_for_update_arg', None) is not None:
            if any(desc.get('entity') is CustomerMediaBatch for desc in statement.column_descriptions):
                changed = True
                db.connection().execute(update(CustomerMediaBatch.__table__).where(
                    CustomerMediaBatch.id == batch_id,
                ).values(status='pending_review'))

    event.listen(db, 'do_orm_execute', update_status)
    try:
        with pytest.raises(service.CustomerMediaConflict, match='当前状态'):
            service.clear_batch_assets(db, batch_id, writer, [asset_id])
    finally:
        event.remove(db, 'do_orm_execute', update_status)
    assert changed
    assert db.get(CustomerMediaAsset, asset_id).deleted_at is None
    assert storage.resolve(asset.object_key).exists()


def test_clear_batch_commit_failure_keeps_database_and_files(db, media, monkeypatch):
    _, _, _, _, writer, batch, asset, storage = media
    batch_id = batch.id
    updated = asyncio.run(service.upload_asset(db, batch_id, writer, _upload_png('second.png'), tags=_sample_tags(db)))
    asset_ids = [asset.id for asset in updated.assets]
    keys = [asset.object_key for asset in updated.assets]

    def fail_commit():
        db.flush()
        raise RuntimeError('simulated commit failure')

    monkeypatch.setattr(db, 'commit', fail_commit)
    with pytest.raises(RuntimeError, match='commit failure'):
        service.clear_batch_assets(db, batch_id, writer, asset_ids)
    assert all(db.get(CustomerMediaAsset, asset_id).deleted_at is None for asset_id in asset_ids)
    assert all(storage.resolve(key).exists() for key in keys)


def test_retry_after_clear_cannot_delete_new_upload(db, media):
    _, _, _, _, writer, batch, asset, storage = media
    batch_id, original_id = batch.id, asset.id
    service.clear_batch_assets(db, batch_id, writer, [original_id])
    updated = asyncio.run(service.upload_asset(db, batch_id, writer, _upload_png('new.png'), tags=_sample_tags(db)))
    new_asset = next(asset for asset in updated.assets if asset.deleted_at is None)
    with pytest.raises(service.CustomerMediaConflict, match='素材已变化'):
        service.clear_batch_assets(db, batch_id, writer, [original_id])
    assert db.get(CustomerMediaAsset, new_asset.id).deleted_at is None
    assert storage.resolve(new_asset.object_key).exists()


def test_clear_batch_storage_failure_does_not_restore_deleted_assets(db, media, monkeypatch, caplog):
    _, _, _, _, writer, batch, asset, storage = media
    asset_id, batch_id = asset.id, batch.id
    asset.playback_key = 'test/playback.mp4'
    asset.thumbnail_key = 'test/poster.jpg'
    db.commit()
    deleted_keys = []

    def fail_delete(key):
        deleted_keys.append(key)
        raise RuntimeError('simulated storage failure')

    monkeypatch.setattr(storage, 'delete', fail_delete)
    service.clear_batch_assets(db, batch_id, writer, [asset_id])
    assert db.get(CustomerMediaAsset, asset_id).deleted_at is not None
    assert len(deleted_keys) == 3
    assert 'orphan after batch clear' in caplog.text
