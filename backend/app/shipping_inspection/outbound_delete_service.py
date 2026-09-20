"""Durable delete intent and tombstone in the existing shipping audit table.

Never writes the business mirror. An uncertain delete is read back, not resent.
"""
import logging

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.invoice.models import Invoice, OkkiOutboundTask
from app.invoice.okki_client import ensure_access_token
from app.shipping_inspection import audit_service, outbound_delete_client as remote, outbound_service
from app.shipping_inspection.models import ShippingOperationEvent

logger = logging.getLogger(__name__)
SCOPE = 'outbound-delete'
DELETED = 'outbound_deleted'
PENDING = 'delete_pending'
UNCERTAIN = 'delete_uncertain'
FAILED = 'delete_failed'


class OutboundDeleteError(ValueError):
    pass


def _commit(db):
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning('Outbound deletion persistence failed: %s', type(exc).__name__)
        print(f'[outbound_delete] persistence failed: {type(exc).__name__}', flush=True)
        raise


def _finish(db, event, action, message):
    event = db.query(ShippingOperationEvent).filter_by(id=event.id).populate_existing().with_for_update().one()
    if event.action == DELETED:
        _commit(db)
        return {'outbound_record_id': event.outbound_record_id, 'deleted': True}
    event.action = action
    event.result = {'status': action, 'message': message, 'checked_at': str(beijing_now())}
    # Task holds stop deletion from causing a new automatic outbound.
    for saved in (event.payload or {}).get('tasks', []):
        task = db.query(OkkiOutboundTask).filter_by(id=saved['id']).with_for_update().first()
        if task and task.status == 'skipped' and task.reason == f'delete_pending:{event.request_id}':
            if action == FAILED:
                if saved.get('created'):
                    db.delete(task)
                else:
                    task.status, task.reason = saved['status'], saved['reason']
            elif action == DELETED:
                task.reason = f'deleted:{event.request_id}'
    _commit(db)
    return {'outbound_record_id': event.outbound_record_id, 'deleted': action == DELETED}


def _mirror_order_ids(db, invoice_id):
    columns = outbound_service._table_columns(db, outbound_service.ITEMS_TABLE)
    if not {'outbound_invoice_id', 'order_id'}.issubset(columns):
        return []
    schema = outbound_service._schema()
    return [str(value) for value in db.execute(text(
        f'SELECT DISTINCT order_id FROM `{schema}`.okki_outbound_record_items '
        'WHERE outbound_invoice_id=:id AND order_id IS NOT NULL'), {'id': invoice_id}).scalars()]


def delete_outbound(db, record, user_id):
    invoice_id = str(record.get('outbound_invoice_id') or '')
    if not invoice_id.isdigit() or int(invoice_id) <= 0:
        raise OutboundDeleteError('该记录尚未生成有效的小满出库单，不能删除')
    # Refreshing credentials is done before reserving an irreversible operation.
    event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=invoice_id).with_for_update().first()
    if event and event.action == DELETED:
        return {'outbound_record_id': record['outbound_record_id'], 'deleted': True}
    token = ensure_access_token(db)
    if event and event.action in (PENDING, UNCERTAIN):
        try:
            current = remote.read(token, invoice_id)
        except remote.DeleteRemoteError as exc:
            raise OutboundDeleteError('删除结果待核对，请稍后重新核对；不会重复发送删除') from exc
        if current is None:
            return _finish(db, event, DELETED, '已核实小满出库单不存在')
        raise OutboundDeleteError('删除正在处理或结果待核对；小满单据仍存在，未重复发送删除')

    current = remote.read(token, invoice_id)
    if current is not None:
        if str(current.get('company_info', {}).get('id')) != str(record.get('company_id')):
            raise OutboundDeleteError('小满客户归属已变化，请刷新后核对')
        if current.get('status') != 1:
            raise OutboundDeleteError('仅支持删除待出库单；已出库单请在小满处理')
        if not isinstance(current.get('record_list'), list):
            raise OutboundDeleteError('小满明细不完整，未删除')
    order_ids = sorted({str(row['order_id']) for row in (current or {}).get('record_list', []) if row.get('order_id')})
    if current is None:
        order_ids = sorted(_mirror_order_ids(db, invoice_id))
    # Match the poller's invoice -> task locking order, so a claimed writer wins
    # before our hold or observes skipped after our durable intent commits.
    invoices = db.query(Invoice).filter(Invoice.xiaoman_order_id.in_(order_ids)).order_by(Invoice.id).with_for_update().all()
    if any(inv.linked_sync_id for inv in invoices):
        raise OutboundDeleteError('关联订单正在同步，请处理完成后再删除')
    tasks = db.query(OkkiOutboundTask).filter(OkkiOutboundTask.order_id.in_(order_ids)).order_by(OkkiOutboundTask.id).with_for_update().all()
    if any(task.status in ('running', 'uncertain') for task in tasks):
        raise OutboundDeleteError('关联自动出库任务正在执行或结果待核对，暂不能删除')
    if any((task.reason or '').startswith('delete_pending:') for task in tasks):
        raise OutboundDeleteError('同一订单的另一张出库单正在删除或待核对，请先完成该操作')
    saved_tasks = [{'id': t.id, 'status': t.status, 'reason': t.reason} for t in tasks]
    # Reconciliation can enqueue a previously missing task after deletion. Reserve
    # its unique order_id now, under the same invoice locks as the poller.
    existing_orders = {t.order_id for t in tasks}
    for inv in invoices:
        if inv.xiaoman_order_id not in existing_orders:
            task = OkkiOutboundTask(invoice_id=inv.id, order_id=inv.xiaoman_order_id,
                                   status='skipped', reason=f'delete_pending:{invoice_id}')
            db.add(task)
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                logger.warning('Outbound task concurrently created before deletion: %s', invoice_id)
                print(f'[outbound_delete] task concurrently created: {invoice_id}', flush=True)
                raise OutboundDeleteError('自动出库任务发生变化，请重新核对后删除') from exc
            tasks.append(task)
            saved_tasks.append({'id': task.id, 'created': True})
    snapshot = {'outbound_invoice_id': invoice_id, 'outbound_no': record['outbound_no'],
                'order_ids': order_ids, 'tasks': saved_tasks, 'before': current}
    if event is None:
        event = audit_service.record(db, PENDING, user_id, record['outbound_record_id'],
            context={'scope': SCOPE, 'source': 'pc'}, request_id=invoice_id, payload=snapshot)
    else:
        snapshot['previous_attempts'] = [*(event.payload or {}).get('previous_attempts', []),
            {'operator_user_id': event.operator_user_id, 'operator_name': event.operator_name,
             'result': event.result}]
        event.action, event.payload = PENDING, snapshot
        actor = db.get(ArkUser, user_id)
        event.operator_user_id = event.login_user_id = user_id
        event.operator_name = event.login_name = actor.real_name if actor else str(user_id)
    event.result = {'status': PENDING, 'started_at': str(beijing_now())}
    for task in tasks:
        task.status, task.reason = 'skipped', f'delete_pending:{invoice_id}'
    try:
        _commit(db)  # Durable intent before POST; concurrent inserts lose here.
    except IntegrityError as exc:
        raise OutboundDeleteError('另一请求正在删除这张出库单，请稍后核对') from exc
    if current is None:
        return _finish(db, event, DELETED, '小满出库单已不存在')

    try:
        remote.remove(token, invoice_id)
    except remote.DeleteRemoteError as exc:
        if not exc.uncertain:
            _finish(db, event, FAILED, str(exc))
            raise OutboundDeleteError(str(exc)) from exc
        # Timeout or ambiguous response: read only, never repeat the POST.
        logger.warning('Outbound deletion outcome uncertain: %s', invoice_id)
        print(f'[outbound_delete] outcome uncertain: {invoice_id}', flush=True)
    try:
        after = remote.read(token, invoice_id)
    except remote.DeleteRemoteError as exc:
        _finish(db, event, UNCERTAIN, str(exc))
        raise OutboundDeleteError('删除已提交但结果待核对，请稍后重新核对') from exc
    if after is not None:
        _finish(db, event, UNCERTAIN, '小满仍返回原单，未确认删除成功')
        raise OutboundDeleteError('小满尚未确认删除，请稍后重新核对；不会重复发送删除')
    return _finish(db, event, DELETED, '小满删除成功并已核实')
