"""Real ZIP bytes + portal authorization, using only isolated SQLite and temporary files."""
from datetime import timedelta
import hashlib
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.asset.models import TagDimension, TagValue
from app.auth.models import ArkUser
from app.commerce_transition.models import PlatformPolicy  # noqa: F401 - register before shared SQLite fixture
from app.core.database import get_db
from app.core.storage import files as storage_files
from app.core.storage.cos import StorageError
from app.core.time import beijing_now
from app.customer_media import archive_service, public_router, storage
from app.customer_media.models import (
    CustomerMediaAsset, CustomerMediaAssetTag, CustomerMediaBatch, CustomerMediaCustomerTag,
    CustomerMediaDownload, CustomerPortalAccount, CustomerPortalSession,
)


@pytest.fixture
def portal(db, tmp_path, monkeypatch):
    config = SimpleNamespace(CUSTOMER_MEDIA_STORAGE_ROOT=str(tmp_path / 'originals'),
                             COS_CACHE_ROOT=str(tmp_path / 'cache'), COS_CACHE_MAX_BYTES=8 * 1024 * 1024)
    for module in [storage, storage_files, archive_service]:
        monkeypatch.setattr(module, 'get_settings', lambda: config)
    user = ArkUser(username='zip-owner', password_hash='unused', real_name='Fixture')
    db.add(user); db.flush()
    account = CustomerPortalAccount(customer_id='ZIP-A', customer_name_snapshot='Client A',
                                    login_email='zip@example.com', password_hash='unused',
                                    is_active=True, session_version=1, created_by=user.id, updated_by=user.id)
    db.add(account); db.flush()
    token = 'local-archive-test-token'
    session = CustomerPortalSession(account_id=account.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                    session_version=1, expires_at=beijing_now() + timedelta(days=1))
    db.add(session)
    # SQLite fixture does not enforce FKs; parent IDs are immaterial to this download-only flow.
    batch = CustomerMediaBatch(task_id=9001, request_id=9001, customer_id='ZIP-A',
                              customer_name_snapshot='Client A', applicant_user_id=user.id, status='published')
    db.add(batch); db.flush()
    dimensions = []
    for name, label in [('customer_product_type', 'Product type'), ('textures_type', 'Textures type'), ('color_names', 'Color names')]:
        dim = TagDimension(name=name, label=label, tag_scope='customer', is_visible=1, is_managed=0)
        db.add(dim); db.flush(); dimensions.append(dim)
    db.commit()
    root = storage.LocalMediaStorage(config.CUSTOMER_MEDIA_STORAGE_ROOT).root

    def add_asset(filename='photo.jpg', tags=('Genius Weft', 'Straight', '#1B'), provider='local'):
        number = db.query(CustomerMediaAsset).count() + 1
        content = b'original-photo-' + str(number).encode()
        key = f'fixture/{number}.jpg'
        path = root / key; path.parent.mkdir(exist_ok=True); path.write_bytes(content)
        asset = CustomerMediaAsset(batch_id=batch.id, file_name=filename, media_type='image',
                                   content_type='image/jpeg', file_size=len(content), sha256=hashlib.sha256(content).hexdigest(),
                                   storage_provider=provider, object_key=key, uploaded_by=user.id)
        db.add(asset); db.flush()
        for dim, labels in zip(dimensions, tags):
            for label in labels if isinstance(labels, list) else [labels]:
                if not label: continue
                value = db.scalar(select(TagValue).where(TagValue.dimension_id == dim.id, TagValue.value == label))
                if value is None:
                    value = TagValue(dimension_id=dim.id, value=label, is_active=1)
                    db.add(value); db.flush()
                    db.add(CustomerMediaCustomerTag(customer_id='ZIP-A', dimension_id=dim.id,
                                                   tag_value_id=value.id, display_value=label, created_by=user.id))
                db.add(CustomerMediaAssetTag(asset_id=asset.id, dimension_id=dim.id, tag_value_id=value.id))
        db.commit()
        return asset, content, path

    app = FastAPI()
    app.add_middleware(public_router.PortalSecurityHeadersMiddleware)
    app.include_router(public_router.router, prefix='/api/customer-media/portal')
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        client.cookies.set(public_router.settings.CUSTOMER_MEDIA_COOKIE_NAME, token)
        yield SimpleNamespace(db=db, client=client, add=add_asset, account=account, session=session,
                              batch=batch, config=config, token=token, root=root)


def download(portal, ids):
    return portal.client.post('/api/customer-media/portal/downloads/zip', json={'asset_ids': ids})


def assert_clean(portal):
    from pathlib import Path
    cache = Path(portal.config.COS_CACHE_ROOT)
    assert not list(cache.glob('customer-media-zip-*'))
    assert not list(cache.rglob('*.reservation'))


def test_selected_files_form_one_valid_zip_and_unselected_files_are_absent(portal):
    first, content, _ = portal.add(tags=('Genius Weft', 'Straight', ['#1B', '#60']))
    second, content2, _ = portal.add(tags=('Genius Weft', None, '#1B'))
    portal.add(filename='not-selected.jpg')
    response = download(portal, [second.id, first.id, first.id])
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert response.headers['cache-control'] == 'private, no-store'
    assert 'attachment' in response.headers['content-disposition']
    with ZipFile(BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {'Genius Weft/Straight/#1B/photo.jpg', 'Genius Weft/Straight/#60/photo.jpg', 'Genius Weft/#1B/photo.jpg'}
        assert archive.read('Genius Weft/Straight/#1B/photo.jpg') == content
        assert archive.read('Genius Weft/Straight/#60/photo.jpg') == content
        assert archive.read('Genius Weft/#1B/photo.jpg') == content2
        assert archive.testzip() is None
    assert len(portal.db.scalars(select(CustomerMediaDownload)).all()) == 2
    assert_clean(portal)


def test_all_selected_files_include_missing_levels_and_deduplicate_names(portal):
    first, a, _ = portal.add(tags=(None, None, None))
    second, b, _ = portal.add(tags=(None, None, None))
    third, c, _ = portal.add(filename='color.jpg', tags=(None, None, '#1B'))
    response = download(portal, [first.id, second.id, third.id])
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ['photo.jpg', 'photo (2).jpg', '#1B/color.jpg']
        assert [archive.read(name) for name in archive.namelist()] == [a, b, c]
    assert_clean(portal)


def test_unused_dimension_alias_from_another_customer_does_not_hide_product_level(portal):
    asset, _, _ = portal.add(tags=('Wig', None, None))
    portal.db.add(TagDimension(name='product_type', label='Product type', sort_order=-1, tag_scope='customer'))
    portal.db.commit()
    with ZipFile(BytesIO(download(portal, [asset.id]).content)) as archive:
        assert archive.namelist() == ['Wig/photo.jpg']


@pytest.mark.parametrize('cause', ['other-customer', 'draft', 'unpublished', 'deleted', 'missing-id'])
def test_inaccessible_selection_fails_as_a_whole_before_opening_storage(portal, monkeypatch, cause):
    asset, _, _ = portal.add()
    ids = [asset.id]
    if cause == 'other-customer': portal.batch.customer_id = 'ZIP-B'
    elif cause in ['draft', 'unpublished']: portal.batch.status = cause
    elif cause == 'deleted': asset.deleted_at = beijing_now()
    else: ids.append(999999)
    portal.db.commit()
    monkeypatch.setattr(archive_service, 'storage_for', lambda _: pytest.fail('unauthorized storage read'))
    response = download(portal, ids)
    assert response.status_code == 404
    assert portal.db.query(CustomerMediaDownload).count() == 0
    assert_clean(portal)


def test_no_cookie_is_unauthorized_and_input_is_bounded(portal):
    for ids in [[], [-1], list(range(1, 5002))]:
        assert download(portal, ids).status_code == 422
    portal.client.cookies.clear()
    assert download(portal, [1]).status_code == 401


@pytest.mark.parametrize('cause', ['missing-file', 'corrupt-file', 'too-large', 'too-many-paths'])
def test_failed_build_returns_no_zip_and_releases_private_files(portal, monkeypatch, cause):
    asset, _, path = portal.add()
    if cause == 'missing-file': path.unlink()
    elif cause == 'corrupt-file': path.write_bytes(b'corrupted')
    elif cause == 'too-large': portal.config.COS_CACHE_MAX_BYTES = 32
    else: monkeypatch.setattr(archive_service, 'MAX_ARCHIVE_ENTRIES', 0)
    response = download(portal, [asset.id])
    assert response.status_code == {'missing-file': 404, 'corrupt-file': 503, 'too-large': 413, 'too-many-paths': 413}[cause]
    assert 'application/zip' not in response.headers['content-type']
    assert portal.db.query(CustomerMediaDownload).count() == 0
    assert_clean(portal)


@pytest.mark.parametrize('change', ['unpublish', 'revoke', 'disable', 'customer'])
def test_access_is_rechecked_after_archive_preparation(portal, monkeypatch, change):
    asset, _, _ = portal.add()
    original_write = archive_service._write_original
    def changed(*args):
        original_write(*args)
        if change == 'unpublish': portal.batch.status = 'unpublished'
        elif change == 'revoke': portal.session.revoked_at = beijing_now()
        elif change == 'disable': portal.account.is_active = False
        else: portal.account.customer_id = 'ZIP-B'
        portal.db.commit()
    monkeypatch.setattr(archive_service, '_write_original', changed)
    response = download(portal, [asset.id])
    assert response.status_code in [401, 404]
    assert portal.db.query(CustomerMediaDownload).count() == 0
    assert_clean(portal)


def test_cloud_original_is_downloaded_once_for_multiple_archive_paths(portal, monkeypatch):
    asset, content, _ = portal.add(tags=('Genius Weft', 'Straight', ['#1B', '#60']), provider='cos')
    calls = []
    class Store:
        def download(self, key, destination, **options):
            calls.append((key, options))
            destination.write_bytes(content)
    monkeypatch.setattr(archive_service, 'storage_for', lambda _: storage.CosMediaStorage(Store()))
    response = download(portal, [asset.id])
    assert response.status_code == 200
    assert calls == [(asset.object_key, {'max_bytes': len(content), 'expected_sha256': asset.sha256})]
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 2
        assert all(archive.read(name) == content for name in archive.namelist())
    assert_clean(portal)


def test_cloud_failure_never_uses_local_original(portal, monkeypatch):
    asset, _, _ = portal.add(provider='cos')
    class Store:
        def download(self, key, destination, **options):
            destination.write_bytes(b'partial')
            raise StorageError('fixture unavailable')
    monkeypatch.setattr(archive_service, 'storage_for', lambda _: storage.CosMediaStorage(Store()))
    assert download(portal, [asset.id]).status_code == 503
    assert_clean(portal)


def test_response_disconnect_always_closes_archive_resources(tmp_path):
    import asyncio
    from contextlib import ExitStack
    path = tmp_path / 'archive.zip'; path.write_bytes(b'zip')
    closed = []
    stack = ExitStack(); stack.callback(lambda: closed.append(True))
    response = public_router._ArchiveResponse(archive_service.PreparedArchive(path, stack))
    async def send(message):
        raise OSError('client disconnected')
    async def receive():
        return {'type': 'http.disconnect'}
    with pytest.raises(OSError):
        asyncio.run(response({'type': 'http', 'method': 'GET', 'headers': []}, receive, send))
    assert closed == [True]
