"""Sync remote deletions into local receipts; business mirrors/media remain intact."""
import logging

from sqlalchemy import text

from app.invoice import okki_client
from app.invoice.okki_client import ensure_access_token
from app.invoice.models import OkkiOutboundTask
from app.shipping_inspection import outbound_presence as presence, outbound_service as records
from app.shipping_inspection import outbound_delete_service as deletion
from app.shipping_inspection.models import ShippingOperationEvent

logger = logging.getLogger(__name__)


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
    # The mirror may already have removed the header while Ark still holds a
    # pending receipt. Use its original remote snapshot, not its shipping date.
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


def reconcile_deleted_outbounds(db):
    """One shared two-pass snapshot per run, never 2 scans per mirror row."""
    candidates = _candidates(db)
    if not candidates:
        return {'checked': 0, 'deleted': 0, 'deferred': 0}
    # Refuse the entire snapshot on malformed boundaries, instead of guessing a
    # date that could exclude a still-active record. All records are read first.
    start = min(presence.creation_floor(row['create_time']) for row in candidates.values())
    # State + attempt counter, not timestamp precision, fences same-second
    # poller completions. Newly created tasks are absent from this snapshot.
    task_versions = {t.id: deletion.task_version(t) for t in db.query(OkkiOutboundTask).all()}
    token = ensure_access_token(db)
    db.commit()
    active = presence.active_ids(token, start)
    columns = records._table_columns(db, records.ITEMS_TABLE)
    if not {'outbound_invoice_id', 'order_id'}.issubset(columns):
        raise records.OutboundTableError('出库镜像缺少订单关联字段，未执行删除对账')
    links = db.execute(text(
        f'SELECT DISTINCT outbound_invoice_id, order_id FROM '
        f'`{records._schema()}`.`{records.ITEMS_TABLE}` WHERE order_id IS NOT NULL'
    )).all()
    retained_orders = {str(order) for identity, order in links if str(identity) in active}
    # A replacement may have reached OKKI before either its header or items
    # reached the mirror. Resolve these active IDs live before touching tasks.
    mirrored_ids = {str(identity) for identity, _ in links}
    for identity in sorted(active - mirrored_ids):
        detail = okki_client._get_json('/v1/invoices/outbound/info', token,
            context='出库删除对账关联核验', params={'outbound_invoice_id': identity})
        if (not isinstance(detail, dict) or str(detail.get('outbound_invoice_id')) != identity
                or not isinstance(detail.get('record_list'), list)
                or any(not isinstance(row, dict) for row in detail['record_list'])):
            raise presence.PresenceError('有效出库单关联未完整同步或核验失败，未执行删除对账')
        retained_orders.update(str(row['order_id']) for row in detail['record_list'] if row.get('order_id'))
    stats = {'checked': len(candidates), 'deleted': 0, 'deferred': 0}
    for identity, record in candidates.items():
        if identity in active:
            continue
        try:
            result = deletion.sync_absent_outbound(db, record, active, task_versions, retained_orders)
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
