"""Sync remote deletions through bounded, persistent creation-day snapshots."""
import hashlib
import json
import logging
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import text

from app.core.time import beijing_now, beijing_today
from app.invoice import okki_client
from app.invoice.okki_client import ensure_access_token
from app.invoice.models import OkkiOutboundTask
from app.shipping_inspection import outbound_presence as presence, outbound_service as records
from app.shipping_inspection import outbound_delete_service as deletion
from app.shipping_inspection.models import OkkiOutboundPresenceDay, ShippingOperationEvent

logger = logging.getLogger(__name__)
MAX_SNAPSHOT_DAYS_PER_RUN = 8
MAX_SNAPSHOT_DETAIL_LOOKUPS = 16
SNAPSHOT_DETAIL_TIMEOUT_SECONDS = 15


def _candidates(db):
    rm = records._record_columns(db)
    columns = records._table_columns(db, records.RECORDS_TABLE)
    if not rm.get('invoice_id') or 'create_time' not in columns:
        raise records.OutboundTableError('出库镜像缺少小满ID或创建时间，未执行删除对账')
    rows = db.execute(text(
        f'SELECT {records._record_select(rm)}, r.create_time FROM '
        f'`{records._schema()}`.`{records.RECORDS_TABLE}` r '
        f'WHERE {records.deleted_clause(db, rm)}'
    )).mappings().all()
    candidates = {str(r['outbound_invoice_id']): dict(r) for r in rows}
    if any(not identity.isdigit() or int(identity) <= 0 for identity in candidates):
        raise records.OutboundTableError('出库镜像存在无效小满ID，未执行删除对账')
    pending = db.query(ShippingOperationEvent).filter(
        ShippingOperationEvent.scope == deletion.SCOPE,
        ShippingOperationEvent.action.in_([deletion.PENDING, deletion.UNCERTAIN, 'delete_abandoned']),
    ).all()
    for event in pending:
        if event.request_id not in candidates:
            payload = event.payload or {}
            candidates[event.request_id] = {
                'outbound_invoice_id': event.request_id, 'outbound_record_id': event.outbound_record_id,
                'outbound_no': payload.get('outbound_no'),
                'create_time': (payload.get('before') or {}).get('create_time'),
            }
    return candidates


def _creation_day(value):
    return date.fromisoformat(presence.creation_floor(value)[:10])


def _days_between(start, end):
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _snapshot_days(db, start_day):
    all_days = _days_between(start_day, beijing_today())
    saved = {
        row.creation_date: row
        for row in db.query(OkkiOutboundPresenceDay).filter(
            OkkiOutboundPresenceDay.creation_date.in_(all_days)
        ).all()
    }
    today = beijing_today()
    recent = [day for day in (today - timedelta(days=1),) if day >= start_day]
    missing_or_error = [day for day in all_days if day not in saved or saved[day].status != 'ready']
    stale = sorted(
        (day for day in all_days if day in saved and saved[day].status == 'ready'),
        key=lambda day: saved[day].refreshed_at,
    )
    ordered = []
    for day in missing_or_error + recent + stale:
        if day not in ordered:
            ordered.append(day)
    # Today is always the final scan and consumes one bounded day slot.  It protects
    # against a newly-created replacement but is never itself deletion evidence.
    historical = [day for day in ordered if day != today][:max(0, MAX_SNAPSHOT_DAYS_PER_RUN - 1)]
    return historical + ([today] if today >= start_day else []), all_days


def _mirror_order_links(db):
    columns = records._table_columns(db, records.ITEMS_TABLE)
    if not {'outbound_invoice_id', 'order_id'}.issubset(columns):
        raise records.OutboundTableError('出库镜像缺少订单关联字段，未执行删除对账')
    rows = db.execute(text(
        f'SELECT DISTINCT outbound_invoice_id, order_id FROM '
        f'`{records._schema()}`.`{records.ITEMS_TABLE}` WHERE order_id IS NOT NULL'
    )).all()
    result = defaultdict(set)
    for identity, order_id in rows:
        result[str(identity)].add(str(order_id))
    return result


def _snapshot_row(db, creation_day):
    row = db.get(OkkiOutboundPresenceDay, creation_day)
    if row is None:
        row = OkkiOutboundPresenceDay(
            creation_date=creation_day, status='pending', active_ids=[], active_versions={},
            detail_order_ids={}, retained_order_ids=[],
            pending_detail_ids=[],
            record_count=0, attempted_at=beijing_now(),
        )
        db.add(row)
    return row


def _mark_snapshot_error(db, creation_day, message):
    db.rollback()
    row = _snapshot_row(db, creation_day)
    row.status = 'error'
    row.last_error = message[:255]
    row.attempted_at = beijing_now()
    db.commit()


def _active_versions(rows):
    return {
        identity: hashlib.sha256(json.dumps(
            rows[identity], sort_keys=True, ensure_ascii=False, default=str,
            separators=(',', ':'),
        ).encode()).hexdigest()
        for identity in sorted(rows, key=int)
    }


def _scan_snapshot_day(db, token, creation_day, mirror_links):
    rows = presence.active_rows_for_day(token, creation_day)
    active_ids = set(rows)
    missing_links = set(active_ids - set(mirror_links))
    ordered_ids = sorted(active_ids, key=int)
    snapshot_hash = hashlib.sha256('\n'.join(ordered_ids).encode()).hexdigest()
    active_versions = _active_versions(rows)
    row = _snapshot_row(db, creation_day)
    old_versions = {str(key): value for key, value in (row.active_versions or {}).items()}
    old_pending = set(str(value) for value in (row.pending_detail_ids or []))
    detail_order_ids = {
        str(key): [str(value) for value in values]
        for key, values in (row.detail_order_ids or {}).items()
        if str(key) in active_ids and isinstance(values, list)
    }
    changed_ids = {
        identity for identity in active_ids
        if identity in old_versions and old_versions[identity] != active_versions[identity]
    }
    pending_ids = (old_pending & active_ids) | changed_ids | {
        identity for identity in missing_links
        if old_versions.get(identity) != active_versions[identity] or identity not in detail_order_ids
    }
    for identity in pending_ids:
        detail_order_ids.pop(identity, None)
    retained_orders = {order_id for order_ids in detail_order_ids.values() for order_id in order_ids}
    for identity in active_ids:
        if identity not in detail_order_ids and identity not in pending_ids:
            retained_orders.update(mirror_links.get(identity, ()))
    row.status = 'pending' if pending_ids else 'ready'
    row.active_ids = ordered_ids
    row.active_versions = active_versions
    row.detail_order_ids = detail_order_ids
    row.retained_order_ids = sorted(retained_orders, key=int)
    row.pending_detail_ids = sorted(pending_ids, key=int)
    row.record_count = len(ordered_ids)
    row.snapshot_hash = snapshot_hash
    row.last_error = None
    row.attempted_at = beijing_now()
    if not pending_ids:
        row.refreshed_at = row.attempted_at
    db.commit()
    return row


def _hydrate_snapshot_day(db, token, row, budget):
    """Persist progress after every detail; budget is shared and charged before I/O."""
    pending_ids = list(row.pending_detail_ids or [])
    retained_orders = set(str(value) for value in (row.retained_order_ids or []))
    detail_order_ids = {
        str(key): [str(value) for value in values]
        for key, values in (row.detail_order_ids or {}).items()
    }
    while pending_ids and budget['remaining'] > 0:
        identity = str(pending_ids[0])
        budget['remaining'] -= 1
        detail = okki_client._get_json(
            '/v1/invoices/outbound/info', token, context='出库删除快照关联核验',
            params={'outbound_invoice_id': identity}, timeout=SNAPSHOT_DETAIL_TIMEOUT_SECONDS,
        )
        if (not isinstance(detail, dict) or str(detail.get('outbound_invoice_id')) != identity
                or not isinstance(detail.get('record_list'), list)
                or any(not isinstance(item, dict) for item in detail['record_list'])):
            raise presence.PresenceError('有效出库单关联未完整同步或核验失败，快照进度已保留')
        orders = sorted({str(item['order_id']) for item in detail['record_list'] if item.get('order_id')}, key=int)
        detail_order_ids[identity] = orders
        retained_orders.update(orders)
        pending_ids.pop(0)
        row.detail_order_ids = detail_order_ids
        row.retained_order_ids = sorted(retained_orders, key=int)
        row.pending_detail_ids = pending_ids
        row.status = 'pending' if pending_ids else 'ready'
        row.last_error = None
        if not pending_ids:
            row.refreshed_at = beijing_now()
        db.commit()
    return not pending_ids


def _confirm_snapshot_day(db, token, row):
    """Close the hydration window before current-day protection is trusted."""
    rows = presence.active_rows_for_day(token, row.creation_date)
    if _active_versions(rows) != (row.active_versions or {}):
        raise presence.PresenceError('当天有效出库单在关联补查期间发生变化，本轮不执行删除')
    row.refreshed_at = beijing_now()
    db.commit()


def _coverage_ready(db, all_days):
    ready = db.query(OkkiOutboundPresenceDay.creation_date).filter(
        OkkiOutboundPresenceDay.creation_date.in_(all_days),
        OkkiOutboundPresenceDay.status == 'ready',
    ).count()
    return ready == len(all_days)


def _retained_orders(db):
    retained = set()
    for values, in db.query(OkkiOutboundPresenceDay.retained_order_ids).filter(
        OkkiOutboundPresenceDay.status == 'ready'
    ).all():
        retained.update(str(value) for value in (values or []))
    return retained


def reconcile_deleted_outbounds(db):
    """Refresh bounded immutable creation-day buckets, then reconcile fresh buckets."""
    candidates = _candidates(db)
    stats = {'checked': 0, 'deleted': 0, 'deferred': 0,
             'snapshot_days': 0, 'snapshot_errors': 0, 'coverage_ready': False}
    if not candidates:
        stats['coverage_ready'] = True
        return stats
    candidates_by_day = defaultdict(dict)
    for identity, record in candidates.items():
        candidates_by_day[_creation_day(record['create_time'])][identity] = record
    selected_days, all_days = _snapshot_days(db, min(candidates_by_day))
    mirror_links = _mirror_order_links(db)
    task_versions = {task.id: deletion.task_version(task) for task in db.query(OkkiOutboundTask).all()}
    token = ensure_access_token(db)
    db.commit()
    refreshed_days = []
    budget = {'remaining': MAX_SNAPSHOT_DETAIL_LOOKUPS}
    today = beijing_today()

    def refresh(creation_day):
        try:
            row = _scan_snapshot_day(db, token, creation_day, mirror_links)
            complete = _hydrate_snapshot_day(db, token, row, budget)
            if complete and creation_day == today:
                _confirm_snapshot_day(db, token, row)
            if complete:
                refreshed_days.append(creation_day)
            stats['snapshot_days'] += 1
        except (presence.PresenceError, okki_client.OkkiApiError) as exc:
            _mark_snapshot_error(db, creation_day, str(exc))
            stats['snapshot_errors'] += 1
            logger.warning('Outbound presence snapshot deferred day=%s: %s', creation_day, exc)
            print(f'[outbound_reconcile] snapshot deferred day={creation_day}: {exc}', flush=True)

    # Hydrate historical work first. Scan today last so its replacement-order
    # protection is as close as possible to the guarded local writes below.
    for creation_day in selected_days:
        if creation_day != today:
            refresh(creation_day)
    if today in selected_days:
        refresh(today)
    stats['coverage_ready'] = _coverage_ready(db, all_days)
    if not stats['coverage_ready']:
        stats['deferred'] = len(candidates)
        return stats

    today_snapshot = db.get(OkkiOutboundPresenceDay, today)
    if today_snapshot is None or today_snapshot.status != 'ready' or today not in refreshed_days:
        stats['coverage_ready'] = False
        stats['deferred'] = len(candidates)
        return stats

    retained_orders = _retained_orders(db)
    stats['deferred'] += len(candidates_by_day.get(today, ()))
    for creation_day in refreshed_days:
        if creation_day == today:
            continue
        snapshot = db.get(OkkiOutboundPresenceDay, creation_day)
        active_ids = set(snapshot.active_ids or [])
        for identity, record in candidates_by_day.get(creation_day, {}).items():
            stats['checked'] += 1
            if identity in active_ids:
                continue
            try:
                other_mirror_orders = {
                    order_id
                    for other_identity, order_ids in mirror_links.items()
                    if other_identity != identity
                    for order_id in order_ids
                }
                result = deletion.sync_absent_outbound(
                    db, record, active_ids, task_versions,
                    retained_orders | other_mirror_orders,
                )
                stats['deleted'] += int(result['deleted'])
            except deletion.OutboundDeleteError as exc:
                db.rollback()
                stats['deferred'] += 1
                logger.warning('Outbound deletion reconciliation deferred id=%s: %s', identity, exc)
                print(f'[outbound_reconcile] deferred id={identity}: {exc}', flush=True)
            except Exception as exc:
                db.rollback()
                logger.warning('Outbound deletion reconciliation failed id=%s: %s', identity, type(exc).__name__)
                print(f'[outbound_reconcile] failed id={identity}: {type(exc).__name__}', flush=True)
                raise
    return stats
