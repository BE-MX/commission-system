"""Read-only carrier preview and signed, content-bound mobile confirmation."""
import hashlib
import json
import logging
import re
import time
from datetime import timedelta

from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.time import beijing_now
from app.shipping_inspection import waybill_scope_service as scope
from app.shipping_inspection.models import ShippingInspection
from app.tracking.models import ShipmentTracking

logger = logging.getLogger(__name__)
from app.shipping_inspection.waybill_country_service import country_code


def existing_check(db, inspection, waybill_no, user_id, roles, permissions, *, lock=False):
    query = db.query(ShipmentTracking).filter(ShipmentTracking.waybill_no == waybill_no,
                                             ShipmentTracking.deleted_at.is_(None))
    rows = (query.with_for_update().populate_existing() if lock else query).all()
    if len(rows) > 1:
        raise ValueError('该运单存在多条跟踪记录，请联系管理员核对')
    row = rows[0] if rows else None
    result = dict(exists=bool(row), blocked=False, carrier=row.carrier if row else None,
                  linked_inspections=0, outside_tracking_scope=False)
    if not row:
        # The upload flow can restore a soft-deleted record. Reject cross-customer
        # history before that restoration makes it visible again to the portal.
        deleted_ids = db.query(ShipmentTracking.id).filter(ShipmentTracking.waybill_no == waybill_no,
            ShipmentTracking.deleted_at.isnot(None)).all()
        if deleted_ids:
            linked = db.query(ShippingInspection).filter(
                ShippingInspection.shipment_tracking_id.in_([identity for identity, in deleted_ids])).all()
            if linked:
                current_customer = scope.customer_id(db, inspection)
                result['blocked'] = any(scope.customer_id(db, other) != current_customer for other in linked)
        return None, result
    # Serialize all writers on the tracking row; current-read associations under MySQL RR.
    query = db.query(ShippingInspection).filter(ShippingInspection.shipment_tracking_id == row.id)
    linked = (query.with_for_update().populate_existing() if lock else query).all()
    current_customer = scope.customer_id(db, inspection)
    result['blocked'] = any(scope.customer_id(db, other) != current_customer for other in linked)
    if result['blocked']:
        return row, dict(exists=True, blocked=True, carrier=None, linked_inspections=0,
                         outside_tracking_scope=True)
    result['linked_inspections'] = len(linked)
    from app.tracking.shipment_service import apply_data_scope
    from app.auth.models import ArkUser
    actor = db.get(ArkUser, user_id)
    visible = apply_data_scope(db.query(ShipmentTracking).filter(ShipmentTracking.id == row.id), db,
        {'sub': str(user_id), 'username': actor.username if actor else '', 'roles': roles,
         'permissions': permissions}).first()
    result['outside_tracking_scope'] = visible is None
    return row, result


def warning(code, message, confirm=False):
    return dict(code=code, message=message, requires_confirmation=confirm)


def system_warnings(db, inspection, carrier, country, recipient_name, destination=None, shipment=None, photo=None):
    from app.shipping_inspection.shipment_link_service import shipment_prefill
    prefill = shipment_prefill(db, inspection, strict=True)
    expected = prefill['recipient_country']
    warnings = []
    for label, value in [('recipient_country', country), ('destination_country', destination),
                         ('ocr_country', photo.ocr_recipient_country if photo else None)]:
        if not value or not expected:
            continue
        left, right = country_code(value), country_code(expected)
        if left and right and left != right:
            warnings.append(warning(label, f'运单寄往 {value}，验货单客户在 {expected}，请确认没有拍错包裹', True))
        elif not left or not right:
            warnings.append(warning(label, f'国家写法暂不能自动核对：{value} / {expected}，请人工确认', True))
    normalized = lambda value: re.sub(r'\W', '', str(value or '')).casefold()
    if recipient_name and normalized(recipient_name) not in {
        normalized(prefill['recipient_name']), normalized(inspection.customer_name)}:
        warnings.append(warning('recipient_name', f'面单收件人 {recipient_name} 与客户资料不一致'))
    if photo and photo.ocr_recipient_name and normalized(photo.ocr_recipient_name) not in {
        normalized(prefill['recipient_name']), normalized(inspection.customer_name)}:
        warnings.append(warning('ocr_recipient_name', f'原图识别收件人 {photo.ocr_recipient_name} 与客户资料不一致'))
    current = scope.invoice_map(db, [inspection]).get(inspection.id, [])
    flags = {scope.is_9610(inv) for inv in current} or {False}
    if shipment:
        linked = db.query(ShippingInspection).filter(ShippingInspection.shipment_tracking_id == shipment.id).all()
        for invoices in scope.invoice_map(db, linked).values():
            flags.update({scope.is_9610(inv) for inv in invoices} or {False})
    if True in flags and carrier.upper() != 'DHL':
        warnings.append(warning('non_dhl', '9610 验货单使用非 DHL 承运商，将在 9610 核对中报异常'))
    if flags == {True, False}:
        warnings.append(warning('mixed_waybill', '同一运单混发 9610 和非 9610 验货单，将在 9610 核对中报异常'))
    from app.shipping_inspection.waybill_export_service import export_baseline, legacy_export_unverified
    baseline = export_baseline(db, inspection.id)
    if inspection.shipment_tracking_id and baseline is not None and (shipment is None or str(shipment.id) != str(baseline)):
        warnings.append(warning('exported_rebind', '本单已导出报关，更换后会在 9610 核对里标为异常'))
    elif inspection.shipment_tracking_id and legacy_export_unverified(db, inspection, current):
        warnings.append(warning('legacy_export_unverified', '该订单存在历史报关导出，但未留验货单关联快照，请核验本包裹申报记录'))
    return warnings


def fingerprint(body):
    values = {key: getattr(body, key, None) for key in (
        'waybill_no', 'carrier', 'recipient_country', 'recipient_name', 'edit_version', 'shipment_version', 'photo_token')}
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def tracking_identity(shipment):
    value = f'{shipment.id}:{shipment.carrier}' if shipment else 'new'
    return hashlib.sha256(value.encode()).hexdigest()


def warnings_digest(warnings):
    return hashlib.sha256(json.dumps(warnings, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sign_preview(inspection_id, user_id, body, sync_result, warnings, destination, shipment=None):
    settings = get_settings()
    return jwt.encode(dict(purpose='inspection-waybill-preview', inspection_id=inspection_id, actor=user_id,
        digest=fingerprint(body), sync_result=sync_result, warnings=[w['code'] for w in warnings if w['requires_confirmation']],
        warning_codes=[w['code'] for w in warnings], warning_digest=warnings_digest(warnings), existing=tracking_identity(shipment),
        destination=destination, exp=int(time.time()) + 86400), settings.JWT_SECRET_KEY, algorithm='HS256')


def verify_preview(inspection_id, user_id, body):
    try:
        claims = jwt.decode(body.preview_token or '', get_settings().JWT_SECRET_KEY, algorithms=['HS256'])
    except JWTError as exc:
        raise ValueError('请先同步物流信息，或同步结果已过期') from exc
    if (claims.get('purpose') != 'inspection-waybill-preview' or claims.get('inspection_id') != inspection_id
            or claims.get('actor') != user_id or claims.get('digest') != fingerprint(body)):
        raise ValueError('运单信息已变化，请重新同步物流信息')
    if not set(claims.get('warnings', [])) <= set(body.confirmed_warnings):
        raise ValueError('请先确认国家核对提醒')
    return claims


async def preview(db, inspection, body, user_id, roles, permissions):
    if 'super_admin' not in roles and 'tracking:write' not in permissions:
        raise ValueError('没有物流单上传权限')
    scope.require_scope(db, inspection, user_id, roles, permissions)
    if inspection.status != 'submitted' or inspection.edit_version != body.edit_version or inspection.shipment_version != body.shipment_version:
        raise ValueError('验货单已变化，请刷新')
    from app.shipping_inspection.waybill_photo_models import ShippingWaybillPhoto
    photo = db.query(ShippingWaybillPhoto).filter_by(token=body.photo_token,
        inspection_id=inspection.id, created_by=user_id).first()
    if photo is None or photo.replaced_at is not None:
        raise ValueError('照片凭证无效，请重新拍照')
    if photo.shipment_tracking_id is None and photo.created_at <= beijing_now() - timedelta(hours=24):
        raise ValueError('照片已过期，请重新拍照')
    shipment, existing = existing_check(db, inspection, body.waybill_no, user_id, roles, permissions)
    carrier = shipment.carrier if shipment else body.carrier
    valid = bool(body.recipient_country.strip()) and (carrier.upper() != 'DHL' or bool(re.fullmatch(r'[0-9]{10}', body.waybill_no)))
    result = dict(format_valid=valid, sync_result='unsupported', tracking=None, existing=existing,
                  warnings=[], can_submit=valid and not existing['blocked'], preview_token=None)
    if not result['can_submit']:
        return result
    from app.tracking.carriers import get_adapter
    adapter = get_adapter(carrier)
    if adapter is None and carrier.upper() in {'DHL', 'FEDEX', 'SF'}:
        result['sync_result'] = 'failed'
    destination = None
    if adapter:
        try:
            tracked = await adapter.track(body.waybill_no)
            result['sync_result'] = 'not_found' if getattr(tracked, 'not_found', False) or (tracked.success and not tracked.events) else 'found' if tracked.success else 'failed'
            destination = getattr(tracked, 'destination_country', None)
            result['tracking'] = dict(status=tracked.current_status, status_text=tracked.current_status_text,
                destination_country=destination, events=[dict(event_time=e.event_time, location=e.location,
                description=e.description) for e in sorted(tracked.events, key=lambda e: e.event_time, reverse=True)[:5]])
        except Exception as exc:
            logger.warning('waybill preview carrier unavailable: %s', type(exc).__name__)
            print(f'waybill preview carrier unavailable: {type(exc).__name__}', flush=True)
            result['sync_result'] = 'failed'
    result['warnings'] = system_warnings(db, inspection, carrier, body.recipient_country, body.recipient_name, destination, shipment, photo)
    result['preview_token'] = sign_preview(inspection.id, user_id, body, result['sync_result'], result['warnings'], destination, shipment)
    return result
