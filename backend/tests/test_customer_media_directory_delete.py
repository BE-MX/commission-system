"""客户目录级删除：权限、批次状态、原件清理和签名预览回归。"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, update

from app.core.database import get_db
from app.customer_media import service
from app.customer_media.models import CustomerMediaAsset, CustomerMediaBatch, CustomerMediaDirectory
from app.customer_media import router as media_router
from app.customer_media.storage import LocalMediaStorage
from app.design.models import DesignDesigner, DesignScheduleTask
from tests.test_customer_media import _add_customer, _payload, _png, _seed_workflow, _upload_png


@pytest.fixture
def media(db, tmp_path, monkeypatch):
    _add_customer(db, "CUST-MEDIA-1", "客户甲")
    applicant, designer, request, task = _seed_workflow(db)
    writer = _payload(designer, "customer_media:write")
    batch = service.get_or_create_batch(db, task.id, writer)
    storage = LocalMediaStorage(tmp_path)
    monkeypatch.setattr(service, "storage_for", lambda provider="local": storage)
    monkeypatch.setattr(media_router, "storage_for", lambda provider="local": storage)
    updated = asyncio.run(service.upload_asset(
        db, batch.id, writer, _upload_png(), directory_name="产品图",
    ))
    asset = updated.assets[0]
    return applicant, designer, request, task, writer, batch, asset, storage


def add_shared_batch(db, media):
    _, _, request, task, writer, _, asset, _ = media
    second_task = DesignScheduleTask(
        request_id=request.id, task_no="DT-MEDIA-002", designer_id=task.designer_id,
        customer_id=request.customer_id, customer_name=request.customer_name, status="in_progress",
    )
    db.add(second_task)
    db.commit()
    second = service.get_or_create_batch(db, second_task.id, writer)
    return asyncio.run(service.upload_asset(
        db, second.id, writer, _upload_png("shared.png"), directory_id=asset.directory_id,
    ))


def test_delete_shared_directory_removes_all_files_and_preserves_unrelated(db, media):
    _, _, _, _, writer, batch, asset, storage = media
    directory_id, asset_id, object_key = asset.directory_id, asset.id, asset.object_key
    second = add_shared_batch(db, media)
    second_asset_id, second_key = second.assets[0].id, second.assets[0].object_key
    updated = asyncio.run(service.upload_asset(db, batch.id, writer, _upload_png("loose.png")))
    loose_id = next(row.id for row in updated.assets if row.file_name == "loose.png")
    assert service.list_batch_directories(db, batch.id, writer)[0]["total_asset_count"] == 2
    service.delete_directory(db, batch.id, directory_id, writer)
    assert db.get(CustomerMediaDirectory, directory_id) is None
    for deleted_id in (asset_id, second_asset_id):
        deleted = db.get(CustomerMediaAsset, deleted_id)
        assert deleted.deleted_at is not None
        assert deleted.directory_id is None
    assert not storage.resolve(object_key).exists()
    assert not storage.resolve(second_key).exists()
    assert db.get(CustomerMediaAsset, loose_id).deleted_at is None
    assert service.list_batch_directories(db, batch.id, writer) == []
    with pytest.raises(service.CustomerMediaNotFound):
        service.delete_directory(db, batch.id, directory_id, writer)


@pytest.mark.parametrize("status", ["pending_review", "published"])
def test_shared_directory_state_rejection_is_atomic(db, media, status):
    _, _, _, _, writer, batch, asset, storage = media
    directory_id, asset_id, key = asset.directory_id, asset.id, asset.object_key
    second = add_shared_batch(db, media)
    second.status = status
    db.commit()
    with pytest.raises(service.CustomerMediaConflict):
        service.delete_directory(db, batch.id, directory_id, writer)
    assert db.get(CustomerMediaDirectory, directory_id)
    assert db.get(CustomerMediaAsset, asset_id).deleted_at is None
    assert storage.resolve(key).is_file()
    assert second.assets[0].deleted_at is None


def test_shared_directory_checks_other_task_writer(db, media):
    _, _, _, _, writer, batch, asset, storage = media
    directory_id, asset_id, key = asset.directory_id, asset.id, asset.object_key
    second = add_shared_batch(db, media)
    other_designer = DesignDesigner(name="其他设计师", email="other@example.com")
    db.add(other_designer)
    db.flush()
    db.get(DesignScheduleTask, second.task_id).designer_id = other_designer.id
    db.commit()
    with pytest.raises(service.CustomerMediaForbidden):
        service.delete_directory(db, batch.id, directory_id, writer)
    assert db.get(CustomerMediaAsset, asset_id).deleted_at is None
    assert db.get(CustomerMediaDirectory, directory_id)
    assert storage.resolve(key).is_file()


def test_directory_rejects_other_customer_and_deletes_empty(db, media):
    applicant, designer, _, _, writer, batch, asset, _ = media
    other = CustomerMediaDirectory(customer_id="OTHER", name="其他客户", created_by=designer.id)
    db.add(other)
    db.commit()
    with pytest.raises(service.CustomerMediaNotFound):
        service.delete_directory(db, batch.id, other.id, writer)
    with pytest.raises(service.CustomerMediaForbidden):
        service.delete_directory(db, batch.id, asset.directory_id, _payload(applicant, "customer_media:write"))
    empty = service.create_directory(db, batch.id, writer, "空目录")
    service.delete_directory(db, batch.id, empty["id"], writer)
    assert db.get(CustomerMediaDirectory, empty["id"]) is None


def test_uploaded_image_signed_url_returns_image_and_deleted_url_returns_404(db, media):
    _, _, _, _, writer, batch, asset, _ = media
    url = service.internal_preview_url(asset.id)
    app = FastAPI()
    app.include_router(media_router.router, prefix="/api/customer-media")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == _png()
        assert client.get(url.replace("token=", "token=x")).status_code == 422
        service.delete_directory(db, batch.id, asset.directory_id, writer)
        assert client.get(url).status_code == 404


def test_upload_refreshes_batch_status_after_waiting_for_directory(db, media):
    _, _, _, _, writer, batch, _, storage = media
    batch_id = batch.id
    original_files = set(storage.root.rglob('*.png'))
    changed = False

    def submit_before_final_lock(state):
        nonlocal changed
        statement = state.statement
        if changed or not state.is_select or getattr(statement, '_for_update_arg', None) is None:
            return
        if any(desc.get('entity') is CustomerMediaBatch for desc in statement.column_descriptions):
            changed = True
            # 模拟目录锁等待期间另一个请求提交；绕过 ORM 同步，保留旧 draft 缓存。
            db.connection().execute(update(CustomerMediaBatch.__table__).where(
                CustomerMediaBatch.id == batch_id,
            ).values(status='pending_review'))

    event.listen(db, 'do_orm_execute', submit_before_final_lock)
    try:
        with pytest.raises(service.CustomerMediaConflict, match='状态已变化'):
            asyncio.run(service.upload_asset(
                db, batch_id, writer, _upload_png('late.png'), directory_name='产品图',
            ))
    finally:
        event.remove(db, 'do_orm_execute', submit_before_final_lock)
    assert changed
    assert set(storage.root.rglob('*.png')) == original_files
