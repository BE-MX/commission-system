"""Selective photo invalidation using stable OKKI detail identities."""
from collections import Counter

from app.shipping_inspection import outbound_service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from app.shipping_inspection.outbound_sync_plan import number, physical, physical_changes


def remote_id(row):
    return 'okki:' + str(row['outbound_record_id'])


def _prefixed(identity):
    return 'okki:' + str(identity)


def _media_type(photo):
    return getattr(photo, 'media_type', 'image') or 'image'


def _signature(row):
    """Product identity that survives OKKI deleting and recreating a detail row.

    Product/SKU identity wins; name+model+unit is the fallback for legacy mirrors
    that never carried the ids. Missing identity stays conservative (no carry).
    """
    product_id = str(row.get('product_id') or '').strip()
    sku_id = str(row.get('sku_id') or '').strip()
    if product_id:
        return ('product', product_id, sku_id)
    name = str(row.get('product_name') or '').strip().casefold()
    if not name:
        return None
    return ('name', name, str(row.get('product_model') or '').strip().casefold(),
            str(row.get('product_unit') or '').strip().casefold())


def _aliases(links, plan):
    """Old local detail id → old remote detail id, limited to this plan's document."""
    old_ids = {_prefixed(row['outbound_record_id']) for row in plan['before']['record_list']
               if row.get('outbound_record_id') is not None}
    aliases = {}
    for row in plan.get('item_links') or []:
        local, key = str(row.get('local_item_id') or ''), _prefixed(row.get('remote_item_id'))
        if local and key in old_ids:
            aliases[local] = key
    for row in links or []:
        local, key = str(row.get('local_item_id') or ''), _prefixed(row.get('remote_item_id'))
        if local and key in old_ids:
            aliases[local] = key
    return aliases


def carry_pairs(plan, after, photos, links, *, changed=None, removed=None, stale_ids=()):
    """Pair deleted/recreated lines whose product identity did not change.

    Returns ``{old order_record_id: new order_record_id}``. Only an unambiguous
    one-to-one product match is carried, and only when the old line already has
    usable (non-stale) photo evidence. Everything else keeps the existing
    conservative re-photograph requirement.
    """
    before = plan['before']['record_list']
    if changed is None or removed is None:
        changed, removed = physical_changes(before, after['record_list'],
                                            plan['material_order_ids'], plan['removed_order_ids'])
    old = {str(row['order_record_id']): row for row in before}
    current = {str(row['order_record_id']): row for row in after['record_list']}
    invalid = {key for key in map(str, set(changed) | set(removed))
               if key in old and physical(old[key])}
    if not invalid:
        return {}
    aliases = _aliases(links, plan)
    stale = set(stale_ids)
    photographed = {aliases.get(str(photo.item_id), str(photo.item_id))
                    for photo in photos
                    if photo.item_id is not None and photo.id not in stale
                    and _media_type(photo) == 'image'}
    old_counts, new_counts = Counter(), Counter()
    for row in old.values():
        signature = _signature(row)
        if signature and physical(row):
            old_counts[signature] += 1
    for row in current.values():
        signature = _signature(row)
        if signature and physical(row):
            new_counts[signature] += 1
    old_by_signature, new_by_signature = {}, {}
    for key in invalid:
        signature = _signature(old[key])
        if signature:
            old_by_signature.setdefault(signature, []).append(key)
    for key, row in current.items():
        if not physical(row) or (key in old and key not in changed):
            continue
        signature = _signature(row)
        if signature:
            new_by_signature.setdefault(signature, []).append(key)
    carried = {}
    for signature, old_keys in old_by_signature.items():
        new_keys = new_by_signature.get(signature) or []
        if (len(old_keys) != 1 or len(new_keys) != 1
                or old_counts[signature] != 1 or new_counts[signature] != 1):
            continue
        old_key, new_key = old_keys[0], new_keys[0]
        old_remote = old[old_key].get('outbound_record_id')
        if old_remote is None or _prefixed(old_remote) not in photographed:
            continue
        # A quantity change is a real shipping change; one photo cannot prove it.
        try:
            if number(old[old_key].get('outbound_count')) != number(current[new_key].get('outbound_count')):
                continue
        except (ValueError, TypeError):
            continue
        carried[old_key] = new_key
    return carried


def uncovered(plan, before, pairs):
    """True when a physical change has no old product identity to inherit."""
    changed, removed = physical_changes(before['record_list'], plan['expected'],
                                        plan['material_order_ids'], plan['removed_order_ids'])
    covered = set(pairs) | set(pairs.values())
    return bool((set(changed) | set(removed)) - covered)


def carry_media(plan, after, links, photos, pairs, *, stale_ids=()):
    """Rebind inherited evidence to the recreated detail; callers audit the movement.

    Binding prefers the current local id so the station groups it under the new
    line immediately; while the mirror still lags it binds the stable remote id
    and read APIs resolve that back to the local id once the mirror catches up.
    """
    if not pairs:
        return []
    old = {str(row['order_record_id']): row for row in plan['before']['record_list']}
    current = {str(row['order_record_id']): row for row in after['record_list']}
    moves = {}
    for old_key, new_key in pairs.items():
        old_row, new_row = old.get(old_key), current.get(new_key)
        if not old_row or not new_row:
            continue
        old_remote, new_remote = old_row.get('outbound_record_id'), new_row.get('outbound_record_id')
        if old_remote is None or new_remote is None:
            continue
        moves[str(old_remote)] = str(new_remote)
    if not moves:
        return []
    old_local = {}
    for row in plan.get('item_links') or []:
        local, remote = str(row.get('local_item_id') or ''), str(row.get('remote_item_id') or '')
        if local and remote:
            old_local[local] = remote
    new_local = {}
    for row in links or []:
        local, remote = str(row.get('local_item_id') or ''), str(row.get('remote_item_id') or '')
        if local and remote:
            new_local[remote] = local
    stale = set(stale_ids)
    moved = []
    for photo in photos:
        if photo.item_id is None or photo.id in stale:
            continue
        item = str(photo.item_id)
        remote = item[5:] if item.startswith('okki:') else old_local.get(item)
        target = moves.get(remote)
        if target is None:
            continue
        bound = new_local.get(target) or _prefixed(target)
        if item == bound:
            continue
        moved.append({'media_id': photo.id, 'from': item, 'to': bound,
                      'old_outbound_record_id': remote, 'new_outbound_record_id': target})
        photo.item_id = bound
    return moved


def changes(plan, after, links, photos, previous, *, pairs=None, allow_carry=True):
    changed_orders, removed_orders = physical_changes(
        plan['before']['record_list'], after['record_list'],
        plan['material_order_ids'], plan['removed_order_ids'])
    all_removed_orders = set(map(str, plan['removed_order_ids']))
    invalid = {remote_id(row) for row in plan['before']['record_list']
               if str(row['order_record_id']) in changed_orders | removed_orders}
    removed = {remote_id(row) for row in plan['before']['record_list']
               if str(row['order_record_id']) in all_removed_orders}
    aliases = _aliases(links, plan)
    stale = set(previous.get('stale_media_ids') or [])
    required = set(previous.get('required_recheck_ids') or [])
    required.difference_update(removed | {local for local, key in aliases.items() if key in removed})
    fees = {remote_id(row) for row in after['record_list'] if not physical(row)}
    required.difference_update(fees | {local for local, key in aliases.items() if key in fees})
    if pairs is None:
        pairs = carry_pairs(plan, after, photos, links, changed=changed_orders,
                            removed=removed_orders, stale_ids=stale) if allow_carry else {}
    old_rows = {str(row['order_record_id']): row for row in plan['before']['record_list']}
    new_rows = {str(row['order_record_id']): row for row in after['record_list']}
    carried_old = {_prefixed(old_rows[key]['outbound_record_id'])
                   for key in pairs if key in old_rows and old_rows[key].get('outbound_record_id') is not None}
    carried_new = {_prefixed(new_rows[key]['outbound_record_id'])
                   for key in pairs.values() if key in new_rows and new_rows[key].get('outbound_record_id') is not None}
    # A recreated line can only carry a requirement created by this same change.
    required.difference_update(carried_new)
    required.difference_update({str(row['local_item_id']) for row in links or []
                                if row.get('local_item_id') is not None
                                and _prefixed(row.get('remote_item_id')) in carried_new})
    material = bool(changed_orders or removed_orders)
    # Old mirrors without stable links cannot safely identify unchanged evidence.
    unknown = material and any(photo.id not in stale and photo.item_id is not None
                              and str(photo.item_id) not in aliases
                              and not str(photo.item_id).startswith('okki:') for photo in photos)
    if unknown:
        stale.update(photo.id for photo in photos)
        required.add('__all_items__')
        required.add('__whole__')
        return sorted(stale), sorted(required)
    effective_invalid = invalid - carried_old
    required_new = {remote_id(row) for row in after['record_list']
                    if str(row['order_record_id']) in changed_orders and physical(row)} - carried_new
    required.update(required_new)
    whole_needed = plan['remark_changed'] or bool(effective_invalid) or bool(required_new)
    for photo in photos:
        if photo.id in stale:
            continue
        if photo.item_id is None:
            if whole_needed:
                stale.add(photo.id)
        elif aliases.get(str(photo.item_id), str(photo.item_id)) in effective_invalid:
            stale.add(photo.id)
    if whole_needed:
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
    Carry-over is disabled here: this path never rewrites media bindings, so a
    recomputed requirement must keep matching the stored (old) local ids.
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
        stale, required = changes(plan, {'record_list': list(actual.values())}, links, old_photos, {},
                                  allow_carry=False)
        if '__all_items__' in required:
            return result
        return {**result, 'stale_media_ids': stale, 'required_recheck_ids': required,
                'selective_recheck_history_id': history.id}
    return result
