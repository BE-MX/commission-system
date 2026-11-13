"""GET-only recovery of a deleted outbound before an explicit invoice sync.

Retire proven accepted updates and the old mirror together. A new successful
order push, then the existing outbound executor, still own regeneration.
"""
import logging
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.time import beijing_now
from app.commerce_transition.models import SendingClaim
from app.invoice import edit_authority, legacy_sending, linked_sync_service as linked
from app.invoice import order_sync_execution as orders, outbound_create_facts
from app.invoice import linked_outbound_service, okki_client
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.models import OkkiOutboundTask, InvoiceLinkedSync, InvoiceSyncLog
from app.invoice.stock_reservations import fenced
from app.receipt import remote
from app.receipt.models import Receipt
from app.shipping_inspection import audit_service, outbound_delete_client, outbound_facts as facts
from app.shipping_inspection import outbound_service as mirror, outbound_sync_plan as plans
from app.shipping_inspection import outbound_sync_state as state
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection, ShippingInspectionPhoto

logger = logging.getLogger(__name__)


def reject(message, status=409):
    raise HTTPException(status, message, headers={'Cache-Control': 'private, no-store'})


def clear(db):
    db.rollback()
    db.expire_all()


def row_state(row):
    return None if row is None else tuple(deepcopy(getattr(row, c.name)) for c in row.__table__.columns)


def candidate(db, invoice):
    """Only one unretired mirror, with every line belonging to this order."""
    rm = mirror._record_columns(db)
    columns = mirror._table_columns(db, mirror.RECORDS_TABLE)
    item_columns = mirror._table_columns(db, mirror.ITEMS_TABLE)
    if not rm['invoice_id'] or 'status' not in columns or not {'outbound_invoice_id', 'order_id'} <= item_columns:
        return None  # No deletion inference; normal push/follow-up guards remain.
    rows = db.execute(text(f"""SELECT r.`{rm['id']}` AS id, r.`{rm['invoice_id']}` AS remote_id,
        r.status FROM `{mirror._schema()}`.`{mirror.RECORDS_TABLE}` r
        WHERE EXISTS (SELECT 1 FROM `{mirror._schema()}`.`{mirror.ITEMS_TABLE}` i
            WHERE i.outbound_invoice_id=r.`{rm['invoice_id']}` AND i.order_id=:order_id)
          AND {mirror.deleted_clause(db, rm)}
        ORDER BY r.`{rm['id']}` LIMIT 2"""), {'order_id': str(invoice.xiaoman_order_id)}).mappings().all()
    if not rows:
        return None
    if len(rows) != 1:
        return None  # Split/manual outbounds retain their normal sync behavior.
    row = rows[0]
    if str(row['status']) != '1':
        return None  # Shipped history never grants a new full-order outbound.
    record = mirror.get_outbound_record(db, str(row['id']), include_deleted=True)
    if (not record or str(record['outbound_invoice_id']) != str(row['remote_id'])
            or str(record['company_id']) != str(invoice.customer_id)
            or record['order_id'] != str(invoice.xiaoman_order_id)):
        return None
    items = db.execute(text(f'SELECT * FROM `{mirror._schema()}`.`{mirror.ITEMS_TABLE}` '
        'WHERE outbound_invoice_id=:identity ORDER BY id'), {'identity': str(row['remote_id'])}).mappings().all()
    if not items or any(str(item['order_id']) != str(invoice.xiaoman_order_id) for item in items):
        return None
    record = {**record, 'recovery_mirror_items': [dict(item) for item in items]}
    return record


def original_chain(db, event):
    if event is None or event.action not in state.ACTIVE:
        return []
    if (event.payload or {}).get('protocol') != 1:
        reject('原出库同步缺少完整发送记录，请人工核对')
    attempt = facts.load(db, event)
    chain = facts.chain(db, attempt)
    for item in chain:
        if not facts.expired(item):
            reject('原出库同步仍在执行租约内，请稍后重新同步')
        fact = facts.get(db, facts.FACT, item.nonce)
        claim = legacy_sending.find(db, 'legacy:outbound-sync:' + item.nonce)
        if (not fact or fact.result.get('result_class') != 'accepted' or not claim
                or claim.state != 'succeeded'
                or str(claim.external_id) != str(item.data['record']['outbound_invoice_id'])):
            reject('原出库发送结果尚未明确，不能因旧单缺失而重新生成')
        if item.data['plan']['before'].get('status') != 1:
            reject('原出库不是待出库状态，不能自动重建')
    return chain


def capture(db, invoice_id, user, linked_id, linked_token, body):
    permissions = ('invoice:write', 'invoice:sync') if body is not None else ('invoice:sync',)
    invoice, actor = edit_authority.prepare_recovery(db, invoice_id, user, *permissions)
    if body is not None:
        if linked.replay(db, invoice, body, int(actor['id']))[0] is not None:
            return None
        if linked.edit_version(invoice) != body.expected_version:
            reject('订单已被他人修改，请刷新后重新编辑')
    if not invoice.xiaoman_order_id or invoice.order_type == 'presale':
        return None
    ensure_active(invoice)
    linked.ensure_idle(invoice, linked_id)
    if linked_id:
        linked.ensure_running(db, invoice, linked_id, linked_token)
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id == invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    if task is None or task.status != 'done':
        return None  # Including existing deleted tombstones: never renew their timestamp.
    if str(task.order_id) != str(invoice.xiaoman_order_id):
        reject('原出库任务与订单身份不一致')
    from app.sales_return.guards import ensure_commercial_editable, ensure_outbound_editable
    ensure_commercial_editable(db, invoice.xiaoman_order_id)
    if (invoice.sync_status == 'sync_uncertain' or orders.facts.unresolved(db, invoice)
            or outbound_create_facts.unresolved(db, invoice.id)
            or db.scalar(select(SendingClaim.id).where(SendingClaim.active_invoice_key == invoice.id)) is not None
            or db.query(Receipt.id).filter(Receipt.invoice_id == invoice.id, Receipt.status == 'active',
                Receipt.sync_status.in_(['syncing', 'uncertain'])).first()):
        reject('原订单、回款或出库创建结果尚未核实，不能自动恢复')
    record = candidate(db, invoice)
    if record is None:
        return None
    ensure_outbound_editable(db, record)
    epoch = legacy_sending.authorize(db, invoice).epoch
    events = db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope == state.SCOPE,
        ShippingOperationEvent.payload['invoice_id'].as_integer() == invoice.id)
        .order_by(ShippingOperationEvent.id).with_for_update().execution_options(populate_existing=True)).all()
    event = db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope == state.SCOPE,
        ShippingOperationEvent.request_id == str(record['outbound_record_id']))
        .with_for_update().execution_options(populate_existing=True))
    if any(e.action in state.ACTIVE and (event is None or e.id != event.id) for e in events):
        reject('存在其他未完成的出库同步，不能整单重建')
    chain = original_chain(db, event)
    if chain and any(item.data['invoice_id'] != invoice.id or
            str(item.data['record']['outbound_invoice_id']) != str(record['outbound_invoice_id']) or
            str(item.data['record']['outbound_record_id']) != str(record['outbound_record_id']) for item in chain):
        reject('原出库发送记录的订单或目标不一致')
    if not chain and facts.unresolved(db, record['outbound_record_id']):
        reject('原出库仍有未结束的发送记录')
    deletion = db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope == 'outbound-delete',
        ShippingOperationEvent.request_id == str(record['outbound_invoice_id']))
        .with_for_update().execution_options(populate_existing=True))
    if deletion:
        if deletion.action == 'delete_failed':
            return None  # Preserve the failed deletion audit and ordinary sync path.
        reject('原出库已有删除处理记录，请核对原任务')
    inspection = db.scalar(select(ShippingInspection).where(
        ShippingInspection.outbound_record_id == str(record['outbound_record_id']))
        .with_for_update().execution_options(populate_existing=True))
    photos = db.scalars(select(ShippingInspectionPhoto).where(ShippingInspectionPhoto.inspection_id == inspection.id)
        .order_by(ShippingInspectionPhoto.id).with_for_update().execution_options(populate_existing=True)).all() if inspection else []
    linked_rows = db.scalars(select(InvoiceLinkedSync).where(InvoiceLinkedSync.invoice_id == invoice.id)
        .order_by(InvoiceLinkedSync.id).with_for_update().execution_options(populate_existing=True)).all()
    binding = plans.digest((orders.capture(db, invoice, {}), epoch, record, row_state(event),
        tuple(row_state(e) for e in events), row_state(inspection), tuple(row_state(p) for p in photos),
        tuple(row_state(r) for r in linked_rows),
        [(a.nonce, facts.fingerprint(db, a), row_state(legacy_sending.find(db, 'legacy:outbound-sync:' + a.nonce))) for a in chain]))
    return invoice, actor, task, record, event, chain, binding


def evidence(db, record, order_id, customer_id):
    token = okki_client.ensure_access_token(db)
    db.commit()  # Credential cache only, never a transaction spanning HTTP.
    observation = outbound_delete_client.observe(token, str(record['outbound_invoice_id']))
    if observation['active']:
        return None
    detail = observation['detail']
    if detail is not None:
        rows = detail.get('record_list')
        if (str(detail.get('outbound_invoice_id')) != str(record['outbound_invoice_id'])
                or type(detail.get('status')) is not int or detail['status'] != 1
                or str((detail.get('company_info') or {}).get('id')) != customer_id
                or not isinstance(rows, list) or not rows
                or any(not isinstance(r, dict) or str(r.get('order_id')) != order_id for r in rows)):
            reject('已删除出库的状态、客户或订单关联发生变化，不能自动重建')
    order = remote.read(db, '/v1/invoices/order/info', {'order_id': order_id})
    if str(order.get('order_id')) != order_id or str(order.get('company_id')) != customer_id:
        reject('小满订单身份已变化，不能自动重建')
    related = linked_outbound_service.find_related(db, order)
    if not isinstance(related, list):
        reject('关联出库证据不完整，请稍后重新同步', 503)
    if related:
        reject('订单已有其他有效出库单，不能重复整单重建')
    # Repeat exact absence after the unrelated-document scan; worker will also
    # recheck every live association before creating a new document.
    if outbound_delete_client.observe(token, str(record['outbound_invoice_id'])) != observation:
        reject('原出库单在核验期间重新出现，请重新核对')
    return {'outbound_invoice_id': str(record['outbound_invoice_id']), 'order_id': order_id,
            'deleted_detail_fingerprint': plans.digest(detail),
            'order_fingerprint': plans.digest(order), 'no_related_outbounds': True,
            'observed_at': beijing_now().isoformat()}


def retire(db, captured, observed):
    invoice, actor, task, record, event, chain, binding = captured
    review = {'resolution': 'accepted_then_remote_deleted' if chain else 'remote_deleted',
              'operator_id': actor['id'], 'evidence': observed, 'binding_fingerprint': binding,
              'prior_sync_log_id': db.scalar(select(InvoiceSyncLog.id).where(
                  InvoiceSyncLog.invoice_id == invoice.id, InvoiceSyncLog.success == 1,
                  InvoiceSyncLog.action.in_(['create', 'update']))
                  .order_by(InvoiceSyncLog.id.desc()).limit(1)) or 0}
    for attempt in chain:
        fingerprint = facts.fingerprint(db, attempt, include_reads=False)
        finished = facts.get(db, facts.FINISH, attempt.nonce)
        if finished is None:
            facts.append(db, facts.FINISH, attempt.nonce, attempt, facts.identity(attempt),
                {'facts_fingerprint': fingerprint, 'resolution': review['resolution'], 'deletion_recovery': review})
        elif finished.result.get('facts_fingerprint') != fingerprint:
            reject('原发送结束后又收到新事实，请人工核对')
    if event is not None and event.action in state.ACTIVE:
        event.action = 'sync_failed'
        event.result = {**(event.result or {}), 'message': '原同步目标已在小满删除；已保留发送事实，等待新版发票同步后重建',
                        'deletion_recovery': review}
    if facts.unresolved(db, record['outbound_record_id']):
        reject('原出库发送记录未完全核销')
    identity = str(record['outbound_invoice_id'])
    audit_service.record(db, 'outbound_deleted', actor['id'], str(record['outbound_record_id']),
        context={'scope': 'outbound-delete', 'source': 'invoice_sync'}, request_id=identity,
        payload={'outbound_invoice_id': identity, 'outbound_no': record['outbound_no'],
                 'order_ids': [str(invoice.xiaoman_order_id)], 'invoice_ids': [invoice.id],
                 'tasks': [{'id': task.id, 'status': task.status, 'reason': task.reason}],
                 'deletion_recovery': review},
        result={'status': 'outbound_deleted', 'message': '重新同步发票前已核实小满旧出库单不存在',
                'checked_at': beijing_now().isoformat()})
    task.status, task.reason = 'skipped', f'deleted:{identity}'
    db.commit()
    return {'outbound_invoice_id': identity, 'deleted': True}


@fenced
def before_sync(db, invoice_id, user, *, linked_id=None, linked_token=None, body=None):
    try:
        first = capture(db, invoice_id, user, linked_id, linked_token, body)
        if first is None:
            clear(db)
            return None
        invoice, _, _, record, _, _, baseline = first
        order_id, customer_id = str(invoice.xiaoman_order_id), str(invoice.customer_id)
        db.commit()
        try:
            observed = evidence(db, record, order_id, customer_id)
        finally:
            clear(db)
        if observed is None:
            return None
        current = capture(db, invoice_id, user, linked_id, linked_token, body)
        if current is None or current[-1] != baseline:
            reject('删除核验期间订单、回款或原出库资料已变化，请重新同步')
        return retire(db, current, observed)
    except HTTPException:
        raise
    except linked.LinkedSyncPending as error:
        raise HTTPException(409, str(error), headers={'Cache-Control': 'private, no-store',
            'X-Ark-Linked-Sync': 'pending', 'X-Ark-Linked-Sync-Id': error.identity}) from None
    except (ValueError, KeyError, TypeError) as error:
        logger.warning('Deleted outbound recovery rejected (%s)', type(error).__name__)
        print('[deleted-outbound] original evidence cannot authorize regeneration', flush=True)
        reject('原出库删除证据暂不能完整核实，请稍后重新同步', 503)
    except SQLAlchemyError:
        logger.warning('Deleted outbound recovery persistence unavailable')
        print('[deleted-outbound] recovery transaction unavailable', flush=True)
        reject('出库删除核验暂未完成，请重新读取原任务', 503)
    finally:
        clear(db)
