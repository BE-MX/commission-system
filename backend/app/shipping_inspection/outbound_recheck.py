"""Selective photo invalidation using stable OKKI detail identities."""
from app.shipping_inspection import outbound_service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent


def physical(row):
    return str(row.get('product_name') or '').strip().casefold() != 'other items'


def remote_id(row):
    return 'okki:' + str(row['outbound_record_id'])


def changes(plan, after, links, photos, previous):
    changed_orders = set(map(str, plan['material_order_ids']))
    removed_orders = set(map(str, plan['removed_order_ids']))
    old = plan['before']['record_list']
    invalid = {remote_id(row) for row in old
               if str(row['order_record_id']) in changed_orders | removed_orders}
    removed = {remote_id(row) for row in old if str(row['order_record_id']) in removed_orders}
    old_ids = {remote_id(row) for row in old}
    aliases = {str(row['local_item_id']): 'okki:' + str(row['remote_item_id']) for row in links
               if 'okki:' + str(row['remote_item_id']) in old_ids}
    stale = set(previous.get('stale_media_ids') or [])
    required = set(previous.get('required_recheck_ids') or [])
    required.difference_update(removed | {local for local, key in aliases.items() if key in removed})
    fees = {remote_id(row) for row in after['record_list'] if not physical(row)}
    required.difference_update(fees | {local for local, key in aliases.items() if key in fees})
    material = bool(changed_orders or removed_orders)
    # Old mirrors without stable links cannot safely identify unchanged evidence.
    unknown = material and any(photo.id not in stale and photo.item_id is not None and str(photo.item_id) not in aliases
                              and not str(photo.item_id).startswith('okki:') for photo in photos)
    if unknown:
        stale.update(photo.id for photo in photos)
        required.add('__all_items__')
    else:
        stale.update(photo.id for photo in photos if (
            aliases.get(str(photo.item_id), str(photo.item_id)) in invalid
            or photo.item_id is None and (material or plan['remark_changed'])))
        required.update(remote_id(row) for row in after['record_list']
                        if str(row['order_record_id']) in changed_orders and physical(row))
    if material or plan['remark_changed']:
        required.add('__whole__')
    return sorted(stale), sorted(required)


def resolve(required, items, links):
    """Expose current display IDs, while persisted requirements keep remote IDs."""
    current = {str(item['item_id']) for item in items}
    aliases = {'okki:' + str(row['remote_item_id']): str(row['local_item_id']) for row in links}
    return [aliases[key] if key in aliases and aliases[key] in current else key for key in required]


def effective_result(db, event, inspection=None):
    """Recover a single legacy blanket round only with a complete audited baseline.

    Reads do not mutate audit data. Successful submission persists the corrected
    evidence and records its provenance. Missing/ambiguous proof stays conservative.
    """
    result = event.result or {} if event else {}
    if not event or event.action != 'sync_done' or '__all_items__' not in result.get('required_recheck_ids', []):
        return result
    inspection = inspection or db.query(ShippingInspection).filter_by(outbound_record_id=event.outbound_record_id).first()
    if not inspection or inspection.status != 'draft':
        return result
    snapshot = result.get('verified')
    if not snapshot or not outbound_service.mirror_matches_snapshot(db, event.outbound_record_id, snapshot):
        return result
    record = outbound_service.get_outbound_record(db, event.outbound_record_id)
    if not record or record.get('mirror_updated_at') != snapshot.get('update_time'):
        return result
    histories = db.query(ShippingOperationEvent).filter_by(
        scope='outbound-sync-history', outbound_record_id=event.outbound_record_id
    ).order_by(ShippingOperationEvent.id.desc()).limit(50).all()
    for history in histories:
        plan = (history.payload or {}).get('plan') or {}
        baseline = plan.get('inspection') or {}
        if (baseline.get('id') != inspection.id or baseline.get('edit_version') != inspection.edit_version - 1
                or not plan.get('material_order_ids') and not plan.get('removed_order_ids')):
            continue
        # Earlier unresolved rounds must never be silently restored.
        prior = history.result or {}
        if prior.get('stale_media_ids') or prior.get('required_recheck_ids'):
            return result
        if set(baseline.get('media_ids') or []) != set(result.get('stale_media_ids') or []):
            return result
        links = outbound_service.inspection_item_links(db, event.outbound_record_id)
        expected = plan.get('expected') or []
        actual = {str(row['remote_item_id']): row for row in links}
        if not expected or len(actual) != len(links) or len(expected) != len(actual):
            return result
        # Recovery requires existing row identities and the full product/quantity baseline.
        fields = ('product_id', 'sku_id', 'product_name', 'product_model', 'product_cn_name',
                  'product_unit', 'order_id', 'order_record_id')
        for row in expected:
            current = actual.get(str(row.get('outbound_record_id')))
            if (not current or any(key not in current or str(current.get(key) or '') != str(row.get(key) or '') for key in fields)
                    or float(current['outbound_count']) != float(row['outbound_count'])):
                return result
        if (snapshot.get('serial_id') != plan.get('serial_after')
                or (snapshot.get('remark') or '').strip() != (plan.get('remark_after') or '').strip()):
            return result
        photos = db.query(ShippingInspectionPhoto).filter_by(inspection_id=inspection.id).all()
        old_photos = [photo for photo in photos if photo.id in baseline['media_ids']]
        if len(old_photos) != len(baseline['media_ids']):
            return result
        stale, required = changes(plan, {'record_list': list(actual.values())}, links, old_photos, {})
        if '__all_items__' in required:
            return result
        return {**result, 'stale_media_ids': stale, 'required_recheck_ids': required,
                'selective_recheck_history_id': history.id}
    return result
