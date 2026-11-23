"""Durable capture, single-use binding and authorized photo metadata."""
from datetime import timedelta
from io import BytesIO
import logging
import re
import secrets

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from app.core.storage import transfers
from app.core.time import beijing_now
from app.shipping_inspection import file_service
from app.shipping_inspection.waybill_photo_models import ShippingWaybillPhoto

logger = logging.getLogger('commission')
DOMAIN = 'shipping-inspection'


def validate_photo(db, inspection_id, user_id, token):
    photo = db.query(ShippingWaybillPhoto).filter_by(token=token).populate_existing().with_for_update().first()
    if photo is None or photo.inspection_id != inspection_id or photo.created_by != user_id:
        raise HTTPException(422, '照片凭证无效，请重新拍照')
    if photo.shipment_tracking_id is None and photo.created_at <= beijing_now() - timedelta(hours=24):
        raise HTTPException(422, '照片已过期，请重新拍照')
    return photo


def mark_replaced(db, inspection_id, user_id, except_photo_id=None):
    rows = db.query(ShippingWaybillPhoto).filter(
        ShippingWaybillPhoto.inspection_id == inspection_id,
        ShippingWaybillPhoto.shipment_tracking_id.isnot(None),
        ShippingWaybillPhoto.replaced_at.is_(None)).with_for_update().all()
    for row in rows:
        if row.id != except_photo_id:
            row.replaced_at = beijing_now()
            row.replaced_by = row.updated_by = user_id


def consume_photo(db, inspection, shipment_id, user_id, photo_token, number_source, sync_result):
    photo = validate_photo(db, inspection.id, user_id, photo_token)
    if photo.shipment_tracking_id is not None:
        if photo.shipment_tracking_id != shipment_id or photo.replaced_at is not None:
            raise HTTPException(409, '照片凭证已使用，请重新拍照')
        return photo
    if number_source not in {'barcode', 'ocr', 'manual'} or sync_result not in {'found', 'not_found', 'failed', 'unsupported', 'skipped'}:
        raise HTTPException(422, '照片来源或同步状态无效')
    mark_replaced(db, inspection.id, user_id, except_photo_id=photo.id)
    photo.shipment_tracking_id = shipment_id
    photo.number_source = number_source
    photo.sync_result = sync_result
    photo.updated_by = user_id
    db.flush()
    return photo


async def _image(upload):
    content = await upload.read(20 * 1024 * 1024 + 1)
    file_service.validate_upload(upload.filename, upload.content_type, len(content))
    try:
        with Image.open(BytesIO(content)) as img:
            if img.format not in {'JPEG', 'PNG', 'WEBP'} or img.width * img.height > 40_000_000:
                raise file_service.FileValidationError('图片格式或尺寸不支持')
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise file_service.FileValidationError('无法读取图片，请重新拍摄') from exc
    return content


async def capture(db, inspection_id, user_id, rectified, original, barcode=''):
    contents = await _image(rectified)
    original_contents = await _image(original)
    if len(contents) + len(original_contents) > 20 * 1024 * 1024:
        raise file_service.FileValidationError('两张照片合计不能超过 20MB，请压缩后重试')
    paths = []
    committing = False
    try:
        for upload, content in ((rectified, contents), (original, original_contents)):
            key = file_service.store_bytes(upload.filename, content)
            paths.append(key)
            transfers.register(db, DOMAIN, key)
        photo = ShippingWaybillPhoto(inspection_id=inspection_id, rectified_path=paths[0], original_path=paths[1],
                                    token=secrets.token_urlsafe(32), created_by=user_id, updated_by=user_id)
        db.add(photo)
        db.flush()
        photo_token, photo_id = photo.token, photo.id
        committing = True
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning('Waybill capture persistence failed: %s', type(exc).__name__)
        print(f'[waybill-photo] persistence failed: {type(exc).__name__}', flush=True)
        # A connection failure during commit can leave a durable receipt. Keep
        # bytes for recovery rather than destroying evidence with uncertain state.
        if not committing:
            for key in paths:
                file_service.remove_file(key)
        raise
    from app.tracking.upload_service import run_ocr
    result = {'ocr_confidence': 'failed', 'recognition_error': None}
    try:
        result.update(await run_ocr(contents, '.' + rectified.filename.rsplit('.', 1)[-1].lower()))
    except Exception as exc:
        logger.warning('Waybill recognition failed: %s', type(exc).__name__)
        print(f'[waybill-photo] recognition failed: {type(exc).__name__}', flush=True)
        result['recognition_error'] = '识别暂时失败，照片已保存，可重拍或手动输入'
    # Store source OCR facts before returning the token. Later user edits cannot
    # erase a mismatching country or recipient from the package evidence.
    try:
        photo.ocr_recipient_country = str(result.get('recipient_country') or '').strip()[:128] or None
        photo.ocr_recipient_name = str(result.get('recipient_name') or '').strip()[:256] or None
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning('Waybill OCR evidence save failed: %s', type(exc).__name__)
        print(f'[waybill-photo] OCR evidence save failed: {type(exc).__name__}', flush=True)
        raise
    barcode = re.sub(r'\s+', '', barcode or '').upper()
    valid_barcode = bool(re.fullmatch(r'(?:[0-9]{10}|[0-9]{12}|[0-9]{15}|1Z[A-Z0-9]{16}|SF[0-9]{13})', barcode))
    result['barcode_conflict'] = result.get('waybill_no') if valid_barcode and result.get('waybill_no') not in (None, '', barcode) else None
    result['number_source'] = 'barcode' if valid_barcode else ('ocr' if result.get('waybill_no') else 'manual')
    if valid_barcode:
        result['waybill_no'] = barcode
        if len(barcode) == 10:
            result['carrier'] = 'DHL'
        elif barcode.startswith(('1Z', 'SF')):
            result['carrier'] = 'UPS' if barcode.startswith('1Z') else 'SF'
    result.update(photo_token=photo_token, photo_id=photo_id)
    return result


def _user_names(db, photos):
    from app.auth.models import ArkUser
    ids = {value for photo in photos for value in (photo.created_by, photo.replaced_by) if value is not None}
    return {u.id: u.real_name or u.username for u in db.query(ArkUser).filter(ArkUser.id.in_(ids)).all()} if ids else {}


def photo_dict(db, photo, users=None):
    users = _user_names(db, [photo]) if users is None else users
    base = f'/api/shipping-inspection/records/{photo.inspection_id}/waybill-photos/{photo.id}'
    return {**{key: getattr(photo, key) for key in ('id', 'inspection_id', 'shipment_tracking_id', 'number_source', 'sync_result', 'created_at', 'created_by', 'replaced_at', 'replaced_by')},
            'created_by_name': users.get(photo.created_by), 'replaced_by_name': users.get(photo.replaced_by),
            'rectified_url': base + '?variant=rectified', 'original_url': base + '?variant=original'}


def list_photos(db, inspection_id):
    rows = db.query(ShippingWaybillPhoto).filter(
        ShippingWaybillPhoto.inspection_id == inspection_id, ShippingWaybillPhoto.shipment_tracking_id.isnot(None)
    ).order_by(ShippingWaybillPhoto.created_at.desc(), ShippingWaybillPhoto.id.desc()).all()
    return photos_dict(db, rows)


def cleanup_expired(db, limit=200):
    rows = db.query(ShippingWaybillPhoto).filter(ShippingWaybillPhoto.shipment_tracking_id.is_(None),
        ShippingWaybillPhoto.created_at <= beijing_now() - timedelta(hours=24)).order_by(ShippingWaybillPhoto.id).limit(limit).with_for_update(skip_locked=True).all()
    paths = []
    for photo in rows:
        for key in (photo.rectified_path, photo.original_path):
            transfers.tombstone(db, DOMAIN, key)
            paths.append(key)
        db.delete(photo)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning('Waybill photo cleanup failed: %s', type(exc).__name__)
        print(f'[waybill-photo] cleanup failed: {type(exc).__name__}', flush=True)
        raise
    for key in paths:
        file_service.remove_file(key)
    return len(rows)


def current_photos(db, inspection_ids):
    """Caller must authorize the input inspections before requesting metadata."""
    if not inspection_ids:
        return {}
    rows = db.query(ShippingWaybillPhoto).filter(
        ShippingWaybillPhoto.inspection_id.in_(inspection_ids),
        ShippingWaybillPhoto.shipment_tracking_id.isnot(None),
        ShippingWaybillPhoto.replaced_at.is_(None)).order_by(ShippingWaybillPhoto.id).all()
    users = _user_names(db, rows)
    return {p.inspection_id: photo_dict(db, p, users) for p in rows}


def photos_dict(db, rows):
    users = _user_names(db, rows)
    return [photo_dict(db, p, users) for p in rows]
