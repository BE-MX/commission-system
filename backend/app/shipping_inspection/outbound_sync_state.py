"""Shared outbound synchronization mutex, durable audit and mirror overlay."""
from sqlalchemy.exc import IntegrityError
from app.shipping_inspection import audit_service
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent

SCOPE = 'outbound-invoice-sync'
ACTIVE = ('sync_pending', 'sync_sending', 'sync_uncertain')
RECHECK = 'recheck_required'
BLOCKED = ACTIVE + (RECHECK,)


def requires_recheck_photo(item):
    """Other Items is a fee row, so it has no physical product to photograph."""
    from app.shipping_inspection.outbound_recheck import physical
    return physical(item)


def can_print_before_recheck(event, mirror_updated_at=None):
    """A scoped exception permits the current outbound sheet, not old inspection evidence."""
    if not event or event.action != 'sync_done':
        return False
    result = event.result or {}
    grant = result.get('print_before_recheck')
    verified = result.get('verified') or {}
    return (bool(result.get('required_recheck_ids')) and isinstance(grant, dict)
            and bool(verified.get('update_time'))
            and grant.get('verified_update_time') == verified['update_time']
            and bool(mirror_updated_at) and str(mirror_updated_at) <= str(verified['update_time']))


def can_allow_print_before_recheck(event, record, inspection):
    if not event or event.action != 'sync_done' or not inspection or inspection.status != 'draft':
        return False
    result = event.result or {}
    verified = result.get('verified') or {}
    mirror_time = record.get('mirror_updated_at')
    return (bool(result.get('required_recheck_ids')) and bool(verified.get('update_time'))
            and bool(mirror_time) and str(mirror_time) <= str(verified['update_time'])
            and not can_print_before_recheck(event, mirror_time))


def ensure_printable(db, record_id, record=None):
    event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=str(record_id)).populate_existing().with_for_update().first()
    if event and (event.action in BLOCKED or
                  ((event.result or {}).get('required_recheck_ids') and not can_print_before_recheck(
                      event, record.get('mirror_updated_at') if record else None))):
        raise ValueError('出库单正在同步或等待重新验货核对，暂不能打印')
    return event


def allow_print_before_recheck(db, record, actor_id, reason):
    """Allow printing this verified outbound while fresh inspection remains mandatory."""
    if len(reason.strip()) < 8:
        raise ValueError('请填写至少8个字符的处理依据')
    record_id = str(record['outbound_record_id'])
    event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=record_id).populate_existing().with_for_update().first()
    result = event.result or {} if event else {}
    verified = result.get('verified') or {}
    if (event is None or event.action != 'sync_done' or not result.get('required_recheck_ids')
            or not verified.get('update_time')):
        raise ValueError('出库单不处于已同步待补验状态，请刷新后核对')
    mirror_time = record.get('mirror_updated_at')
    if not mirror_time or str(mirror_time) > str(verified['update_time']):
        raise ValueError('小满出库资料已再次变化，请先同步并核对')
    inspection = db.query(ShippingInspection).filter_by(outbound_record_id=record_id).populate_existing().with_for_update().first()
    if inspection is None or inspection.status != 'draft':
        raise ValueError('原验货单状态已变化，请刷新后核对')
    if can_print_before_recheck(event, mirror_time):
        return {'print_before_recheck': True, 'recheck_required': True}
    event.result = {**result, 'print_before_recheck': {
        'verified_update_time': verified['update_time'], 'inspection_id': inspection.id,
    }}
    audit_service.record(db, 'allow_print', actor_id, record_id, inspection=inspection,
                         context={'scope': f'pc:{actor_id}', 'source': 'pc'},
                         payload={'reason': reason, 'verified_update_time': verified['update_time']},
                         result={'recheck_required': True})
    from app.shipping_inspection.outbound_sync_service import commit
    commit(db)
    return {'print_before_recheck': True, 'recheck_required': True}


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
        from app.shipping_inspection.outbound_service import mirror_matches_snapshot
        if mirror_matches_snapshot(db, record['outbound_record_id'], snapshot):
            return None
    return snapshot


def apply_header(db, record, *, event=None):
    snapshot = overlay(db, record, event=event)
    if snapshot:
        record.update(outbound_no=snapshot.get('serial_id') or record.get('outbound_no'),
                      remark=snapshot.get('remark'), item_count=len(snapshot['items']),
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
    from app.shipping_inspection.outbound_recheck import effective_result, resolve
    from app.shipping_inspection import outbound_service
    result = effective_result(db, event)
    required = result.get('required_recheck_ids', [])
    if any(key.startswith('okki:') for key in required):
        required = resolve(required, outbound_service.list_outbound_items(db, record_id),
                           outbound_service.inspection_item_links(db, record_id))
    return result.get('stale_media_ids', []), required


def ensure_submission_ready(db, record_id, actor, inspection):
    event = lock(db, record_id, actor)
    if event.action in BLOCKED:
        raise ValueError('出库单资料待同步或重新验货，暂不能提交验货')
    from app.shipping_inspection.outbound_recheck import effective_result, resolve
    result = effective_result(db, event, inspection)
    required = result.get('required_recheck_ids') or []
    if required:
        from app.shipping_inspection.models import ShippingInspectionPhoto
        stale = set(result.get('stale_media_ids') or [])
        photos = db.query(ShippingInspectionPhoto).filter_by(inspection_id=inspection.id, media_type='image').with_for_update().all()
        fresh = {str(photo.item_id) if photo.item_id is not None else '__whole__'
                 for photo in photos if photo.id not in stale}
        needed = set(required)
        all_items = '__all_items__' in needed
        if all_items or needed - {'__whole__'}:
            from app.shipping_inspection import outbound_service
            items = outbound_service.list_outbound_items(db, record_id, use_overlay=False)
            links = outbound_service.inspection_item_links(db, record_id)
            needed = set(resolve(needed, items, links))
            aliases = {'okki:' + str(row['remote_item_id']): str(row['local_item_id']) for row in links}
            fresh.update(aliases[key] for key in list(fresh) if key in aliases)
            if all_items and not items:
                raise ValueError('出库明细尚未刷新，请稍后重新验货')
            if all_items:
                needed.remove('__all_items__')
                needed.update(str(item['item_id']) for item in items)
            needed.difference_update(str(item['item_id']) for item in items if not requires_recheck_photo(item))
        missing = needed - fresh
        if missing:
            raise ValueError('变更后的出库明细尚未补拍验货照片，请重新验货后提交')
        if not fresh:
            raise ValueError('每个发货单至少上传一张当前版本的照片')
    return event


def persist_recovered_evidence(db, event, actor, inspection):
    """Called only after submission version and evidence guards have passed."""
    from app.shipping_inspection.outbound_recheck import effective_result
    result = effective_result(db, event, inspection)
    if result != (event.result or {}):
        event.result = result
        audit_service.record(db, 'selective_recheck_recovered', actor, inspection.outbound_record_id, inspection=inspection,
                             context={'scope': 'outbound-sync-history', 'source': 'inspection_submit'},
                             payload={'history_id': result['selective_recheck_history_id']},
                             result={'stale_media_ids': result['stale_media_ids'],
                                     'required_recheck_ids': result['required_recheck_ids']})
