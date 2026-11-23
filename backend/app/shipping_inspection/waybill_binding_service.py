"""Transactional binding shared by PC and mobile; no tracking ownership transfer."""
from app.auth.service import get_live_user_authorization
from app.shipping_inspection import audit_service, waybill_scope_service as scope, waybill_preview_service as preview


def mobile_evidence(db, inspection, body, user_id, shipment=None):
    from app.shipping_inspection.waybill_photo_service import validate_photo
    if not body.photo_token:
        raise ValueError('请先拍摄并保存物流单照片')
    photo = validate_photo(db, inspection.id, user_id, body.photo_token)
    if photo.shipment_tracking_id and (shipment is None or photo.shipment_tracking_id != shipment.id
                                      or inspection.shipment_tracking_id != shipment.id or photo.replaced_at is not None):
        raise ValueError('照片凭证已使用，请重新拍摄')
    # Durable evidence is the receipt for a committed operation. Mutable customer/
    # export warnings and expired preview JWTs must not turn a lost response into failure.
    if photo.shipment_tracking_id is not None:
        return {'sync_result': photo.sync_result, 'completed_retry': True}, []
    claims = preview.verify_preview(inspection.id, user_id, body)
    created_here = shipment is not None and getattr(body, '_created_tracking_id', None) == shipment.id
    if not created_here and claims.get('existing') != preview.tracking_identity(shipment):
        raise ValueError('运单记录已变化，请重新同步物流信息')
    if not body.recipient_country.strip():
        raise ValueError('请填写收件国家')
    carrier = shipment.carrier if shipment else body.carrier
    warnings = preview.system_warnings(db, inspection, carrier, body.recipient_country,
                                       body.recipient_name, claims.get('destination'), shipment, photo)
    if ({w['code'] for w in warnings} != set(claims.get('warning_codes', []))
            or claims.get('warning_digest') != preview.warnings_digest(warnings)
            or not {w['code'] for w in warnings if w['requires_confirmation']} <= set(claims.get('warnings', []))):
        raise ValueError('核对信息已变化，请重新同步物流信息并确认')
    return claims, warnings


def bind(db, inspection_id, body, user_id):
    from app.shipping_inspection import service
    from app.auth.models import ArkPermission
    # Same first lock as cross_border.write_transaction: export snapshots and rebinds
    # cannot interleave. The permission is seeded even when no export exists yet.
    db.query(ArkPermission.id).filter(ArkPermission.code == 'cross_border:write').with_for_update().first()
    roles, permissions = get_live_user_authorization(db, user_id)
    mobile = getattr(body, 'source', 'pc') == 'mobile'
    if 'super_admin' not in roles:
        if not {'shipping_inspection:write', 'shipping_inspection:admin'} & set(permissions):
            raise ValueError('没有验货单编辑权限')
        required = {'tracking:write'} if mobile else {'tracking:read', 'tracking:read_all', 'tracking:write'}
        if not required & set(permissions):
            raise ValueError('没有物流跟踪访问权限')
    inspection = service._lock_inspection(db, inspection_id)
    if inspection is None or inspection.status != 'submitted' or inspection.edit_version != body.edit_version:
        raise ValueError('验货单已变化，请重新打开后操作')
    scope.require_scope(db, inspection, user_id, roles, permissions)
    shipment, check = preview.existing_check(db, inspection, body.waybill_no, user_id, roles, permissions, lock=True)
    if shipment is None:
        raise ValueError('物流跟踪中没有该运单')
    if check['blocked']:
        raise ValueError('这张运单已关联到另一位客户的验货单，很可能拍错了包裹，请核对手里的包裹')
    claims, warnings = mobile_evidence(db, inspection, body, user_id, shipment) if mobile else ({}, [])
    if claims.get('completed_retry'):
        return service.shipment_brief(db, inspection)
    repeated = inspection.shipment_tracking_id == shipment.id
    if not repeated and inspection.shipment_version != body.shipment_version:
        raise ValueError('物流单关联已变化，请重新打开后核对')
    from app.shipping_inspection.waybill_photo_service import consume_photo, mark_replaced
    if getattr(body, 'photo_token', None):
        consume_photo(db, inspection, shipment.id, user_id, body.photo_token,
                      body.number_source, claims.get('sync_result', 'skipped'))
    elif not repeated:
        mark_replaced(db, inspection.id, user_id)
    if repeated:
        return service.shipment_brief(db, inspection)
    old_tracking_id = inspection.shipment_tracking_id
    from app.shipping_inspection.waybill_export_service import export_baseline
    baseline = export_baseline(db, inspection.id)
    exported = baseline is not None and str(baseline) != str(shipment.id)
    inspection.shipment_tracking_id = shipment.id
    inspection.shipment_version += 1
    inspection.updated_by = user_id
    audit_service.record(db, 'shipment_bound', user_id, inspection.outbound_record_id, inspection=inspection,
        context={'source': getattr(body, 'source', 'pc')}, payload={
            'shipment_tracking_id': shipment.id, 'previous_shipment_tracking_id': old_tracking_id,
            'number_source': getattr(body, 'number_source', 'manual'), 'sync_result': claims.get('sync_result', 'skipped'),
            'checks': [w['code'] for w in warnings], 'exported_rebind': exported,
            'owner_fallback': getattr(body, '_owner_fallback', False)})
    db.flush()
    return service.shipment_brief(db, inspection)
