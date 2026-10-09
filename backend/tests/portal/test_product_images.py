from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import Column, MetaData, Table, select
from test_mapping_service import catalog, managed, portal_metadata, auth_context
from test_auth_service import send_code, verify
from app.asset.models import Asset, AssetPermission
from app.portal import image_service as service
from app.portal.models import CatalogGrant
from app.portal.schemas import CatalogImageInput
from app.portal.errors import PortalError


@pytest.fixture
def images(catalog, tmp_path, monkeypatch):
    ctx, items = catalog
    metadata = MetaData()
    for model in (Asset, AssetPermission):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=c.nullable) for c in model.__table__.columns))
    metadata.create_all(ctx.db.get_bind())
    path = tmp_path / 'image.png'
    Image.new('RGB', (80, 60), 'red').save(path)
    asset = Asset(file_name='Product photo.png', file_type='image', file_format='png',
        storage_path='image.png', file_size=path.stat().st_size, uploader_id=1, status='latest')
    ctx.db.add(asset); ctx.db.flush()
    permission = AssetPermission(asset_id=asset.id, permission_group='all', allow_preview=1, allow_download=1)
    ctx.db.add(permission); ctx.db.commit()
    monkeypatch.setattr(service.transfers, 'managed', lambda domain: False)
    monkeypatch.setattr(service.transfers, 'get_settings', lambda: SimpleNamespace(ASSET_STORAGE_ROOT=str(tmp_path)))
    challenge, code = send_code(ctx)
    _, _, token = verify(ctx, challenge, code)
    return ctx, items[0], asset, permission, token


def bind(values):
    ctx, item, asset, _, _ = values
    result = service.bind(ctx.db, 1, item.public_id, item.row_version,
        CatalogImageInput(asset_id=str(asset.id), asset_reference=service.approved_reference(asset, None), reason='Approved external product image'))
    ctx.db.commit()
    return result


def test_bind_deliver_reencode_and_remove(images):
    ctx, item, asset, _, token = images
    result = bind(images)
    assert result['image_asset_id'] == str(asset.id)
    data = service.customer_image(ctx.db, token, item.public_id, item.row_version)
    with Image.open(BytesIO(data)) as decoded:
        assert decoded.format == 'JPEG' and decoded.size == (80, 60)
    old_version = item.row_version
    service.bind(ctx.db, 1, item.public_id, item.row_version, CatalogImageInput(asset_id=None, reason='Removed'))
    ctx.db.commit()
    with pytest.raises(PortalError): service.customer_image(ctx.db, token, item.public_id, old_version)
    with pytest.raises(PortalError): service.customer_image(ctx.db, token, item.public_id, item.row_version)


@pytest.mark.parametrize('change', ['offline', 'private', 'preview', 'download', 'missing', 'svg', 'path', 'oversize'])
def test_invalid_or_restricted_asset_cannot_be_bound(images, change):
    ctx, item, asset, permission, _ = images
    if change == 'offline': asset.status = 'offline'
    if change == 'private': permission.permission_group = 'specific'
    if change == 'preview': permission.allow_preview = 0
    if change == 'download': permission.allow_download = 0
    if change == 'missing': ctx.db.delete(permission)
    if change == 'svg': asset.file_format = 'svg'
    if change == 'path': asset.storage_path = '../outside.png'
    if change == 'oversize': asset.file_size = service.MAX_BYTES + 1
    ctx.db.commit()
    with pytest.raises(PortalError) as error: bind(images)
    assert error.value.status == 404 and item.image_asset_id is None


@pytest.mark.parametrize('change', ['grant', 'offline', 'preview', 'account'])
def test_old_url_rechecks_current_authority(images, change):
    ctx, item, asset, permission, token = images
    bind(images)
    if change == 'grant': ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id == item.id)).status = 'disabled'
    if change == 'offline': asset.status = 'offline'
    if change == 'preview': permission.allow_preview = 0
    if change == 'account': ctx.account.status = 'disabled'
    ctx.db.commit()
    with pytest.raises(PortalError): service.customer_image(ctx.db, token, item.public_id, item.row_version)


def test_authority_changed_during_io_is_rechecked(images, monkeypatch):
    ctx, item, _, permission, token = images
    bind(images)
    original = service.render
    def revoke(ticket):
        assert not ctx.db.in_transaction(), 'File IO must not hold authority or catalog locks'
        result = original(ticket)
        permission.allow_preview = 0; ctx.db.commit()
        return result
    monkeypatch.setattr(service, 'render', revoke)
    with pytest.raises(PortalError): service.customer_image(ctx.db, token, item.public_id, item.row_version)


def test_binding_version_and_secondary_asset_permission(images, monkeypatch):
    ctx, item, asset, _, _ = images
    bind(images)
    with pytest.raises(PortalError) as caught:
        service.bind(ctx.db, 1, item.public_id, 1, CatalogImageInput(asset_id=str(asset.id), asset_reference=service.approved_reference(asset, None), reason='stale'))
    assert caught.value.code == 'VERSION_CONFLICT'
    original = service.admin.employee_principal
    def limited(db, actor_id, permission):
        if permission == 'asset:admin': raise PortalError('ACTION_FORBIDDEN', 'denied', 403)
        return original(db, actor_id, permission)
    monkeypatch.setattr(service.admin, 'employee_principal', limited)
    with pytest.raises(PortalError) as caught: service.list_assets(ctx.db, 1)
    assert caught.value.status == 403


def test_asset_version_replacement_needs_new_portal_approval(images):
    ctx, item, asset, _, token = images
    bind(images)
    original_version = item.row_version
    asset.current_version_id = 12345; ctx.db.commit()
    with pytest.raises(PortalError) as caught: service.customer_image(ctx.db, token, item.public_id, original_version)
    assert caught.value.status == 404
    bind(images)
    assert service.customer_image(ctx.db, token, item.public_id, item.row_version).startswith(b'\xff\xd8')


def test_storage_errors_are_controlled_and_do_not_expose_provider_detail(images, monkeypatch):
    from app.core.storage.cos import StorageError
    from contextlib import contextmanager
    ctx, item, _, _, token = images
    bind(images)
    @contextmanager
    def unavailable(*args):
        raise StorageError('secret-bucket/path/credential')
        yield
    monkeypatch.setattr(service.transfers, 'materialize', unavailable)
    with pytest.raises(PortalError) as caught: service.customer_image(ctx.db, token, item.public_id, item.row_version)
    assert caught.value.status == 503 and caught.value.code == 'IMAGE_STORAGE_UNAVAILABLE'
    assert 'secret-bucket' not in str(caught.value)


def test_admin_preview_binding_rejects_version_changed_after_preview(images):
    ctx, item, asset, _, _ = images
    data, reference = service.admin_preview(ctx.db, 1, asset.id)
    assert data.startswith(b'\xff\xd8')
    asset.current_version_id = 678; ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.bind(ctx.db, 1, item.public_id, item.row_version,
            CatalogImageInput(asset_id=str(asset.id), asset_reference=reference, reason='Checked image'))
    assert caught.value.code == 'IMAGE_CHANGED' and item.image_asset_id is None


def test_customer_image_http_has_no_public_path_and_rechecks_grant(images, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as customer_http
    ctx, item, _, permission, token = images
    bind(images)
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(customer_http, 'get_settings', lambda: ctx.settings)
    app = FastAPI(); app.include_router(customer_http.router, prefix='/api/portal/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
                headers={'X-Real-IP': '203.0.113.1'}) as client:
            path = f'/api/portal/v1/catalog/{item.public_id}/image?version={item.row_version}'
            assert (await client.get(path)).status_code == 401
            client.cookies.set('__Host-portal_session', token)
            response = await client.get(path)
            assert response.status_code == 200 and response.headers['content-type'] == 'image/jpeg'
            assert response.headers['cache-control'] == 'no-store' and response.headers['x-content-type-options'] == 'nosniff'
            assert 'location' not in response.headers
            assert (await client.get(path.replace(str(item.public_id), str(uuid4())))).status_code == 404
            permission.allow_preview = 0; ctx.db.commit()
            denied = await client.get(path)
            assert denied.status_code == 404 and denied.json()['data']['error_code'] == 'IMAGE_UNAVAILABLE'
            assert 'image.png' not in denied.text
    asyncio.run(scenario())
