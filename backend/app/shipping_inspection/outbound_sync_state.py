"""Shared outbound synchronization mutex, durable audit and mirror overlay."""
from sqlalchemy.exc import IntegrityError
from app.shipping_inspection import audit_service
from app.shipping_inspection.models import ShippingOperationEvent

SCOPE = 'outbound-invoice-sync'
ACTIVE = ('sync_pending', 'sync_sending', 'sync_uncertain')
RECHECK = 'recheck_required'
BLOCKED = ACTIVE + (RECHECK,)


def ensure_printable(db, record_id):
    event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=str(record_id)).populate_existing().with_for_update().first()
    if event and (event.action in BLOCKED or (event.result or {}).get('required_recheck_ids')):
        raise ValueError('出库单正在同步或等待重新验货核对，暂不能打印')
    return event


def lock(db, record_id, actor):
    event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=str(record_id)).populate_existing().with_for_update().first()
    if event is None:
        try:
            with db.begin_nested():
                event = audit_service.record(db, 'sync_idle', actor, str(record_id),
                    context={'scope': SCOPE, 'source': 'pc'}, request_id=str(record_id), payload={}, result={})
                db.flush()
        except IntegrityError:
            event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=str(record_id)).populate_existing().with_for_update().one()
    return event


def ensure_invoice_idle(db, invoice):
    event = db.query(ShippingOperationEvent.id).filter(
        ShippingOperationEvent.scope == SCOPE, ShippingOperationEvent.action.in_(ACTIVE),
        ShippingOperationEvent.payload['invoice_id'].as_integer() == invoice.id).with_for_update().first()
    if event:
        raise ValueError('出库单正在同步或结果待核对，请先在出库单完成核对')


def overlay(db, record, *, event=None):
    if not record:
        return None
    if event is None:
        event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=str(record['outbound_record_id'])).first()
    result = (event.result or {}) if event else {}
    snapshot = result.get('verified')
    if not snapshot:
        return None
    mirror_time = record.get('mirror_updated_at')
    if mirror_time and str(mirror_time) > snapshot['update_time']:
        return None
    if mirror_time and str(mirror_time) == snapshot['update_time']:
        from app.shipping_inspection.outbound_service import list_outbound_items
        items = list_outbound_items(db, record['outbound_record_id'], use_overlay=False)
        def signature(rows):
            keys = ('product_id', 'product_name', 'sku', 'unit', 'size', 'color', 'spec')
            return sorted(tuple(str(r.get(k) or '') for k in keys) + (float(r['qty']),) for r in rows)
        if signature(items) == signature(snapshot['items']) and (record.get('remark') or '') == (snapshot.get('remark') or ''):
            return None
    return snapshot


def apply_header(db, record, *, event=None):
    snapshot = overlay(db, record, event=event)
    if snapshot:
        record.update(remark=snapshot.get('remark'), item_count=len(snapshot['items']),
                      total_qty=sum(x['qty'] for x in snapshot['items']))
    return record


def ensure_inspection_idle(db, record_id, actor):
    # Inspection writers take this same row lock before creating their draft.
    event = lock(db, record_id, actor)
    if event.action in BLOCKED:
        raise ValueError('出库单正在同步或等待重新验货核对，请先处理出库资料')
    from app.shipping_inspection import outbound_service
    if overlay(db, outbound_service.get_outbound_record(db, record_id), event=event):
        raise ValueError('出库单已更新，验货资料正在刷新，请稍后重新扫码')


def evidence(db, record_id):
    event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=str(record_id)).first()
    result = event.result or {} if event else {}
    return result.get('stale_media_ids', []), result.get('required_recheck_ids', [])


def ensure_submission_ready(db, record_id, actor, inspection):
    event = lock(db, record_id, actor)
    if event.action in BLOCKED:
        raise ValueError('出库单资料待同步或重新验货，暂不能提交验货')
    required = (event.result or {}).get('required_recheck_ids') or []
    if required:
        from app.shipping_inspection.models import ShippingInspectionPhoto
        stale = set((event.result or {}).get('stale_media_ids') or [])
        photos = db.query(ShippingInspectionPhoto).filter_by(inspection_id=inspection.id, media_type='image').with_for_update().all()
        fresh = {str(photo.item_id) if photo.item_id is not None else '__whole__'
                 for photo in photos if photo.id not in stale}
        needed = set(required)
        if '__all_items__' in needed:
            needed.remove('__all_items__')
            from app.shipping_inspection import outbound_service
            items = outbound_service.list_outbound_items(db, record_id, use_overlay=False)
            if not items:
                raise ValueError('出库明细尚未刷新，请稍后重新验货')
            needed.update(str(item['item_id']) for item in items)
        missing = needed - fresh
        if missing:
            raise ValueError('变更后的出库明细尚未补拍验货照片，请重新验货后提交')
    return event
