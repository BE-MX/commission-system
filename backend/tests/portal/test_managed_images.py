"""Managed-storage image contract; local cache fixture, never a real COS request."""
from types import SimpleNamespace
import pytest
from test_product_images import images, catalog, managed, portal_metadata, auth_context
from app.core.storage.models import StorageTransfer
from app.core.storage.cos import file_digest
from app.portal import image_service as service
from app.portal.errors import PortalError
from app.portal.schemas import CatalogImageInput


@pytest.fixture
def cloud_image(images, tmp_path, monkeypatch):
    ctx, item, asset, _, token = images
    StorageTransfer.__table__.create(ctx.db.get_bind())
    path = tmp_path / 'image.png'
    size, digest = file_digest(path)
    record = StorageTransfer(id=service.transfers.transfer_id('asset', asset.storage_path),
        domain='asset', object_key=asset.storage_path, source_instance='other-instance',
        file_size=size, sha256=digest, content_type='image/png', status='ready')
    ctx.db.add(record); ctx.db.commit()
    monkeypatch.setattr(service.transfers, 'managed', lambda domain: True)
    monkeypatch.setattr(service.transfers, 'get_settings', lambda: SimpleNamespace(
        COS_INSTANCE_ID='reader-instance', COS_LOCAL_OWNER='other-instance', ASSET_STORAGE_ROOT=str(tmp_path)))
    calls = []
    def cached(domain, key):
        calls.append((domain, key))
        assert not ctx.db.in_transaction()
        return path
    monkeypatch.setattr(service.transfers, 'cached_path', cached)
    data, reference = service.admin_preview(ctx.db, 1, asset.id)
    assert data.startswith(b'\xff\xd8')
    service.bind(ctx.db, 1, item.public_id, item.row_version,
        CatalogImageInput(asset_id=str(asset.id), asset_reference=reference, reason='Approved managed version'))
    ctx.db.commit()
    return ctx, item, asset, token, record, path, calls


def test_ready_managed_image_uses_verified_cache_and_reencodes(cloud_image):
    ctx, item, asset, token, _, _, calls = cloud_image
    assert service.customer_image(ctx.db, token, item.public_id, item.row_version).startswith(b'\xff\xd8')
    assert calls == [('asset', asset.storage_path), ('asset', asset.storage_path)]


@pytest.mark.parametrize('change,status', [('pending', 503), ('deleted', 404), ('missing', 503), ('corrupt_cache', 503), ('changed_digest', 404)])
def test_managed_image_fails_closed(cloud_image, change, status):
    ctx, item, _, token, record, path, calls = cloud_image
    if change == 'missing': ctx.db.delete(record)
    elif change == 'corrupt_cache': path.write_bytes(b'not the registered image')
    elif change == 'changed_digest': record.sha256 = '0' * 64
    else: record.status = change
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.customer_image(ctx.db, token, item.public_id, item.row_version)
    assert caught.value.status == status
    assert 'image.png' not in caught.value.message and 'other-instance' not in caught.value.message
    if change != 'corrupt_cache': assert len(calls) == 1
