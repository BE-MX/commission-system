"""Image approval and post-IO authorization on real owned MySQL connections."""
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest
from sqlalchemy import Column, MetaData, Table, select, text
from sqlalchemy.orm import Session

from app.asset.models import Asset, AssetPermission
from app.portal import image_service as service, admin_service
from app.portal.errors import PortalError
from app.portal.models import CatalogItem, CatalogGrant
from app.portal.schemas import CatalogImageInput, AccountUpdate


@pytest.fixture(scope='session')
def image_schema(service_schema):
    metadata = MetaData()
    for model in (Asset, AssetPermission):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=False if c.primary_key else True) for c in model.__table__.columns))
    metadata.create_all(service_schema.engine)


@pytest.fixture
def image_case(trade, image_schema, tmp_path, monkeypatch):
    ctx = trade
    path = tmp_path / 'product.png'
    Image.new('RGB', (80, 60), 'red').save(path)
    monkeypatch.setattr(service.transfers, 'managed', lambda domain: False)
    monkeypatch.setattr(service.transfers, 'get_settings', lambda: SimpleNamespace(ASSET_STORAGE_ROOT=str(tmp_path)))
    with Session(ctx.engine) as db:
        asset = Asset(file_name='Product.png', file_type='image', file_format='png', storage_path='product.png',
            file_size=path.stat().st_size, uploader_id=ctx.admin, status='latest')
        db.add(asset); db.flush()
        db.add(AssetPermission(asset_id=asset.id, permission_group='all', allow_preview=1, allow_download=1))
        db.commit()
        _, reference = service.admin_preview(db, ctx.admin, asset.id)
        item = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
        result = service.bind(db, ctx.admin, ctx.item_id, item.row_version,
            CatalogImageInput(asset_id=str(asset.id), asset_reference=reference, reason='Approve test image'))
        db.commit()
        ctx.asset_id, ctx.image_version, ctx.reference = asset.id, result['row_version'], reference
    return ctx


def test_actual_mysql_image_approval_delivery_and_stale_reference(image_case):
    ctx = image_case
    with Session(ctx.engine) as db:
        content = service.customer_image(db, ctx.token, ctx.item_id, ctx.image_version)
        with Image.open(BytesIO(content)) as image:
            assert image.format == 'JPEG' and image.size == (80, 60)
        assert not db.in_transaction()
    with Session(ctx.engine) as writer:
        writer.get(Asset, ctx.asset_id).file_size += 1
        writer.commit()
    with Session(ctx.engine) as db:
        with pytest.raises(PortalError) as caught:
            service.bind(db, ctx.admin, ctx.item_id, ctx.image_version,
                CatalogImageInput(asset_id=str(ctx.asset_id), asset_reference=ctx.reference, reason='Stale preview'))
        assert caught.value.code == 'IMAGE_CHANGED'
        db.rollback()
        with pytest.raises(PortalError) as caught:
            service.customer_image(db, ctx.token, ctx.item_id, ctx.image_version)
        assert caught.value.status == 404


@pytest.mark.parametrize('change', ['permission', 'version', 'grant', 'account'])
def test_actual_mysql_image_revocation_commits_during_io(image_case, monkeypatch, change):
    ctx = image_case
    original = service.render
    with Session(ctx.engine) as reader, Session(ctx.engine) as writer:
        reader_id = reader.scalar(text('SELECT CONNECTION_ID()'))
        writer_id = writer.scalar(text('SELECT CONNECTION_ID()'))
        assert reader_id != writer_id
        reader.commit(); writer.commit()
        def render_and_revoke(ticket):
            assert not reader.in_transaction(), 'Storage IO must release reader transaction'
            content = original(ticket)
            if change == 'permission':
                writer.scalar(select(AssetPermission).where(AssetPermission.asset_id == ctx.asset_id)).allow_preview = 0
            elif change == 'version':
                writer.get(Asset, ctx.asset_id).file_size += 1
            elif change == 'grant':
                item = writer.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
                writer.scalar(select(CatalogGrant).where(CatalogGrant.access_id == ctx.access_id, CatalogGrant.catalog_item_id == item.id)).status = 'disabled'
            else:
                admin_service.update_account(writer, ctx.admin, ctx.account_public_id, ctx.account_version,
                    AccountUpdate(status='disabled', reason='Revoke while image is decoded'))
            writer.commit()
            return content
        monkeypatch.setattr(service, 'render', render_and_revoke)
        with pytest.raises(PortalError) as caught:
            service.customer_image(reader, ctx.token, ctx.item_id, ctx.image_version)
        assert caught.value.status in (401, 403, 404)
        reader.rollback()


@pytest.mark.parametrize('change', ['permission', 'version'])
def test_actual_mysql_admin_preview_rechecks_after_io(image_case, monkeypatch, change):
    ctx = image_case
    original = service.render
    with Session(ctx.engine) as reader, Session(ctx.engine) as writer:
        assert reader.scalar(text('SELECT CONNECTION_ID()')) != writer.scalar(text('SELECT CONNECTION_ID()'))
        reader.commit(); writer.commit()
        def replace(ticket):
            assert not reader.in_transaction()
            content = original(ticket)
            if change == 'permission':
                writer.scalar(select(AssetPermission).where(AssetPermission.asset_id == ctx.asset_id)).allow_download = 0
            else:
                writer.get(Asset, ctx.asset_id).file_size += 1
            writer.commit()
            return content
        monkeypatch.setattr(service, 'render', replace)
        with pytest.raises(PortalError) as caught:
            service.admin_preview(reader, ctx.admin, ctx.asset_id)
        assert caught.value.status == (404 if change == 'permission' else 409)
        reader.rollback()
