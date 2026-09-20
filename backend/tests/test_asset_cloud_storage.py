import io
import zipfile

import pytest
from fastapi import HTTPException

from app.asset.models import Asset, AssetPermission
from app.asset import batch_service, media_service
from app.core.config import get_settings
from app.core.storage import transfers
from app.core.storage.models import StorageTransfer


@pytest.fixture
def asset_cloud(db, tmp_path, monkeypatch):
    settings = get_settings()
    for name, value in {'COS_ENABLED_DOMAINS':['asset'], 'COS_MANAGED_DOMAINS':['asset'],
                        'COS_INSTANCE_ID':'office', 'COS_LOCAL_OWNER':'office',
                        'ASSET_STORAGE_ROOT':str(tmp_path)}.items():
        monkeypatch.setattr(settings, name, value)
    path = tmp_path / 'photo.jpg'
    path.write_bytes(b'local original')
    asset = Asset(file_name='photo.jpg', file_type='image', file_format='jpg',
                  storage_path='photo.jpg', file_size=14, uploader_id=1)
    db.add(asset)
    transfers.register(db, 'asset', 'photo.jpg')
    db.commit()
    return asset.id


def test_pending_asset_preview_and_batch_read_from_owner_without_cloud(db, asset_cloud, monkeypatch):
    monkeypatch.setattr(transfers, 'CosObjectStore', lambda *a: pytest.fail('LAN read must not wait for COS'))
    response = media_service.preview(db, 'photo.jpg')
    assert response.path.read_bytes() == b'local original'
    data, _ = batch_service.batch_download(db, [asset_cloud])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.read('photo.jpg') == b'local original'
    assert db.query(StorageTransfer).one().status == 'pending'


def test_preview_rejects_unreferenced_private_keys_and_disabled_preview(db, asset_cloud):
    with pytest.raises(HTTPException) as caught:
        media_service.preview(db, 'shipping-inspection/private.jpg')
    assert caught.value.status_code == 404
    db.add(AssetPermission(asset_id=asset_cloud, allow_preview=0, allow_download=1))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        media_service.preview(db, 'photo.jpg')
    assert caught.value.status_code == 404


def test_pending_asset_cannot_use_another_hosts_stale_copy(db, asset_cloud, monkeypatch):
    monkeypatch.setattr(get_settings(), 'COS_INSTANCE_ID', 'beijing')
    with pytest.raises(HTTPException) as caught:
        media_service.preview(db, 'photo.jpg')
    assert caught.value.status_code == 503
