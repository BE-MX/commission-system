"""Managed product imagery: authorized binding, bounded reads, final scope recheck."""
from io import BytesIO
import base64
import hashlib
import json
import logging
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException
from sqlalchemy import func, select

from app.asset.models import Asset, AssetPermission
from app.core.storage import transfers
from app.core.storage.cos import StorageError, validate_key
from app.portal import admin_service as admin, auth_service, catalog_admin_service
from app.portal.domain import require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CatalogGrant, CatalogItem

logger = logging.getLogger('commission')
MAX_BYTES = 20 * 1024 * 1024
FORMATS = ('jpg', 'jpeg', 'png', 'webp')


def eligible():
    # Binding is an explicit portal publication decision. Restricted internal
    # groups and missing permissions are never eligible for external publication.
    return select(Asset).join(AssetPermission, AssetPermission.asset_id == Asset.id).where(
        Asset.status == 'latest', Asset.file_type == 'image', Asset.file_format.in_(FORMATS),
        Asset.file_size > 0, Asset.file_size <= MAX_BYTES,
        AssetPermission.permission_group == 'all', AssetPermission.allow_preview == 1,
        AssetPermission.allow_download == 1)


def asset_row(db, asset_id):
    row = db.scalar(eligible().where(Asset.id == int(asset_id)).with_for_update()
                    .execution_options(populate_existing=True))
    if row is None:
        reject('IMAGE_UNAVAILABLE', 'This product image is not available.', 404)
    try:
        validate_key(row.storage_path)
    except ValueError:
        reject('IMAGE_UNAVAILABLE', 'This product image is not available.', 404)
    return row


def storage_snapshot(db, key):
    try:
        return transfers.snapshot(db, 'asset', key)
    except HTTPException as error:
        reject('IMAGE_UNAVAILABLE' if error.status_code == 404 else 'IMAGE_STORAGE_UNAVAILABLE',
               'This product image is temporarily unavailable.', 404 if error.status_code == 404 else 503)
    except StorageError as error:
        storage_failure(error)


def storage_failure(error):
    logger.warning('Portal image storage failed type=%s', type(error).__name__)
    print(f'[portal-image] storage failed type={type(error).__name__}', flush=True)
    reject('IMAGE_STORAGE_UNAVAILABLE', 'The product image is temporarily unavailable. Please retry.', 503)


def approved_reference(asset, record):
    # 20-digit asset ID + ':' + 43-char SHA256 fits the existing 64-char opaque
    # managed asset reference. No unsigned ID alone constitutes publication.
    payload = {'asset_id': asset.id, 'version_id': asset.current_version_id,
               'key': asset.storage_path, 'size': asset.file_size, 'format': asset.file_format,
               'sha256': record.get('sha256') if record else None}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).digest()
    return str(asset.id) + ':' + base64.urlsafe_b64encode(digest).decode().rstrip('=')


def list_assets(db, actor_id, *, keyword='', page=1, page_size=20):
    admin.begin(db, actor_id, 'portal_site:admin')
    admin.employee_principal(db, actor_id, 'asset:admin')
    query = eligible()
    if keyword:
        query = query.where(Asset.file_name.contains(keyword, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Asset.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': [{'id': str(row.id), 'name': row.file_name, 'format': row.file_format}
                      for row in rows], 'total': total, 'page': page, 'page_size': page_size}


def bind(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id, 'portal_site:admin')
    admin.employee_principal(db, actor_id, 'asset:admin')
    site = admin.site_for_admin(db)
    item = db.scalar(select(CatalogItem).where(CatalogItem.site_id == site.id,
        CatalogItem.public_id == str(public_id)).with_for_update().execution_options(populate_existing=True))
    if item is None:
        reject('RESOURCE_NOT_FOUND', '商品不存在或不属于当前站点。', 404)
    require_version(item.row_version, expected)
    reference = None
    if body.asset_id is not None:
        asset = asset_row(db, body.asset_id)
        reference = approved_reference(asset, storage_snapshot(db, asset.storage_path))
        if reference != body.asset_reference:
            reject('IMAGE_CHANGED', '素材版本已变化，请重新预览并确认。', 409)
    previous = item.image_asset_id
    item.image_asset_id = reference
    item.row_version += 1
    impact = catalog_admin_service._invalidate(db, item)
    db.add(AuditEvent(actor_type='employee', actor_id=actor['id'], object_type='catalog_item',
        object_public_id=item.public_id, action='catalog.image_bound', before_version=expected,
        after_version=item.row_version, reason=body.reason, trace_id=str(uuid4()),
        safe_diff_json={'previous_image_asset_id': previous, 'image_asset_id': item.image_asset_id}))
    db.flush()
    return {**catalog_admin_service.view(item), **impact}


def ticket(db, token, item_id, version):
    principal, _ = auth_service.authenticate(db, token)
    item = db.scalar(select(CatalogItem).join(CatalogGrant, CatalogGrant.catalog_item_id == CatalogItem.id).where(
        CatalogItem.public_id == str(item_id), CatalogItem.site_id == principal.site.id,
        CatalogItem.status == 'published', CatalogItem.row_version == version,
        CatalogGrant.access_id == principal.access.id, CatalogGrant.status == 'enabled')
        .with_for_update().execution_options(populate_existing=True))
    if item is None or not item.image_asset_id:
        reject('IMAGE_UNAVAILABLE', 'This product image is not available.', 404)
    asset_id, separator, digest = item.image_asset_id.partition(':')
    if not separator or not asset_id.isdecimal() or len(asset_id) > 20 or len(digest) != 43:
        reject('IMAGE_UNAVAILABLE', 'This product image needs approval.', 404)
    asset = asset_row(db, asset_id)
    record = storage_snapshot(db, asset.storage_path)
    if approved_reference(asset, record) != item.image_asset_id:
        reject('IMAGE_UNAVAILABLE', 'This product image needs approval.', 404)
    return {'asset_id': asset.id, 'key': asset.storage_path, 'version_id': asset.current_version_id,
            'record': record}


def render(ticket):
    # Storage/network and decoding occur after the caller releases DB locks.
    try:
        with transfers.materialize('asset', ticket['key'], ticket['record']) as path:
            with path.open('rb') as stream:
                content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            reject('IMAGE_UNAVAILABLE', 'This product image is not available.', 404)
        with Image.open(BytesIO(content)) as source:
            if source.format not in ('JPEG', 'PNG', 'WEBP') or source.width * source.height > 16000000:
                reject('IMAGE_UNAVAILABLE', 'This product image is not available.', 404)
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1200, 1200))
            rgba = image.convert('RGBA')
            clean = Image.new('RGB', rgba.size, 'white')
            clean.paste(rgba, mask=rgba.getchannel('A'))
            output = BytesIO(); clean.save(output, format='JPEG', quality=85)
            return output.getvalue()
    except HTTPException as error:
        reject('IMAGE_UNAVAILABLE' if error.status_code == 404 else 'IMAGE_STORAGE_UNAVAILABLE',
               'This product image is temporarily unavailable.', 404 if error.status_code == 404 else 503)
    except StorageError as error:
        storage_failure(error)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        logger.warning('Portal image decode failed type=%s', type(error).__name__)
        print(f'[portal-image] decode failed type={type(error).__name__}', flush=True)
        reject('IMAGE_UNAVAILABLE', 'This product image is not available.', 404)


def customer_image(db, token, item_id, version):
    before = ticket(db, token, item_id, version)
    db.commit()
    content = render(before)
    after = ticket(db, token, item_id, version)
    if before != after:
        reject('IMAGE_CHANGED', 'The product image changed. Please refresh.', 409)
    db.commit()
    return content


def admin_preview(db, actor_id, asset_id):
    def current():
        admin.begin(db, actor_id, 'portal_site:admin')
        admin.employee_principal(db, actor_id, 'asset:admin')
        asset = asset_row(db, asset_id)
        record = storage_snapshot(db, asset.storage_path)
        return {'key': asset.storage_path, 'record': record}, approved_reference(asset, record)
    before, reference = current()
    db.commit()
    content = render(before)
    after, latest = current()
    if reference != latest or before != after:
        reject('IMAGE_CHANGED', '素材版本已变化，请重新预览。', 409)
    db.commit()
    return content, reference
