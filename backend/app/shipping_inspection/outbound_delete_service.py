"""Durable delete intent and tombstone in the existing shipping audit table.

Never writes the business mirror. An uncertain delete is read back, not resent.
"""
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.invoice.models import Invoice, OkkiOutboundTask
from app.invoice import legacy_sending
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
    event_id, remote_id = event.id, str(event.request_id)
    legacy_sending.ownership.lock_policy(db)
    keys=deepcopy((event.payload or {}).get('sending_claims',[]))
    if action==DELETED:
        conflict = False
        for key in keys:
            claim = legacy_sending.finish(db,key,'succeeded',{'original_request_readback':True,'deleted':True},remote_id)
            conflict = conflict or (claim is not None and claim.state != 'succeeded')
        if keys:
            _commit(db)  # Late original evidence must survive subsequent route rejection.
            legacy_sending.ownership.lock_policy(db)
        if conflict:
            raise OutboundDeleteError('原出库删除证据冲突，办理权已冻结，请核对原任务')
    snapshot = deepcopy(event.payload or {})
    for identity in sorted(snapshot.get('invoice_ids', [])):
        expected = snapshot.get('authority_epochs', {}).get(str(identity),
            snapshot.get('authority_epochs', {}).get(identity))
        legacy_sending.authorize(db, identity, expected)
    event = db.query(ShippingOperationEvent).filter_by(id=event_id).populate_existing().with_for_update().one()
    if event.action == DELETED:
        _commit(db)
        return {'outbound_record_id': event.outbound_record_id, 'deleted': True}
    event.action = action
    event.result = {'status': action, 'message': message, 'checked_at': str(beijing_now())}
    # Task holds stop deletion from causing a new automatic outbound.
    for saved in (event.payload or {}).get('tasks', []):
        task = db.query(OkkiOutboundTask).filter_by(id=saved['id']).with_for_update().first()
        if task and task.status == 'skipped' and task.reason in (
            f'delete_pending:{event.request_id}', f'delete_abandoned:{event.request_id}',
        ):
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


def delete_outbound(db, record, user_id, *, expected_order_id=None, expected_snapshot=None):
    return _delete_outbound(db, record, user_id, expected_order_id=expected_order_id,
                            expected_snapshot=expected_snapshot)


def _current_delete_actor(db, user_id, record=None):
    """Recheck installed live grants and source scope in each claim phase."""
    from app.portal.authority import lock_authority
    from app.portal.access_policy import employee_principal
    from app.portal.errors import PortalError
    lock_authority(db, force=True)
    try:
        actor = employee_principal(db, user_id, 'shipping_inspection:delete')
    except PortalError as exc:
        raise HTTPException(exc.status, '当前账号无权删除出库单') from None
    actor = {**actor, 'sub': str(actor['id'])}
    if record is not None:
        from app.shipping_inspection.router import _outbound_scope
        scope = _outbound_scope(db, actor)
        if scope is not None:
            current = outbound_service.get_outbound_record(db, str(record['outbound_record_id']),
                okki_user_id=scope, include_deleted=True)
            if current is None or str(current.get('outbound_invoice_id')) != str(record.get('outbound_invoice_id')):
                raise HTTPException(404, '出库单不存在或当前归属已变化')
    return actor


def task_version(task):
    return (task.id, task.status, task.reason, task.attempts, task.updated_at)


def sync_absent_outbound(db, record, active_ids, task_versions, retained_orders):
    """Scheduler-only receipt for a verified complete active-list snapshot. No POST."""
    if str(record['outbound_invoice_id']) in active_ids:
        raise OutboundDeleteError('小满出库单仍在有效列表，不能标记删除')
    return _delete_outbound(db, record, 0, missing=True, task_versions=task_versions,
                            retained_orders=retained_orders)


def _delete_outbound(db, record, user_id, *, missing=False, task_versions=None, retained_orders=(),
                     expected_order_id=None, expected_snapshot=None):
    from app.portal.authority import lock_authority
    from app.sales_return.guards import ensure_outbound_editable
    lock_authority(db, force=True)
    ensure_outbound_editable(db, record)
    invoice_id = str(record.get('outbound_invoice_id') or '')
    if not invoice_id.isdigit() or int(invoice_id) <= 0:
        raise OutboundDeleteError('该记录尚未生成有效的小满出库单，不能删除')
    if record.get('transaction_mode') == 'local':
        raise OutboundDeleteError('方舟独立批次请使用本地取消流程')
    if db.new or db.dirty or db.deleted:
        raise OutboundDeleteError('删除前存在未提交修改，请先保存后核对')
    db.rollback()  # Entry callers may only supply a clean read snapshot.
    if not missing:
        _current_delete_actor(db, user_id)
    # Refreshing credentials is done before reserving an irreversible operation.
    event = db.query(ShippingOperationEvent).filter_by(scope=SCOPE, request_id=invoice_id).populate_existing().first()
    event_before=deepcopy((event.action,event.payload,event.result)) if event else None
    if event and event.action == DELETED:
        return {'outbound_record_id': record['outbound_record_id'], 'deleted': True}
    db.rollback()
    token = None if missing else ensure_access_token(db)
    db.commit()  # Credential writes only; no transaction spans provider reads.
    # Resolve every known Ark route before even resuming an old delete entry.
    known_orders = ((event_before[1] or {}).get('order_ids', []) if event_before else
        [str(expected_order_id)] if expected_order_id is not None else _mirror_order_ids(db, invoice_id))
    known_ids=[value for (value,) in db.query(Invoice.id).filter(Invoice.xiaoman_order_id.in_(known_orders)).order_by(Invoice.id)]
    recovering = bool(event_before and event_before[0] in (PENDING, UNCERTAIN, 'delete_abandoned'))
    if recovering:
        legacy_sending.ownership.lock_policy(db)
        for identity in known_ids:
            legacy_sending.ownership._lock_authority(db, identity)
    else:
        for identity in known_ids:
            legacy_sending.authorize(db, identity)
    db.commit()
    if event_before and event_before[0] in (PENDING, UNCERTAIN, 'delete_abandoned'):
        try:
            current = None if missing else remote.read(token, invoice_id)
        except remote.DeleteRemoteError as exc:
            raise OutboundDeleteError('删除结果待核对，请稍后重新核对；不会重复发送删除') from exc
        if current is None:
            return _finish(db, event, DELETED, '已核实小满出库单不存在')
        if event_before[0] == 'delete_abandoned':
            raise OutboundDeleteError('原删除已人工终止，请在小满处理后重新核对，禁止重发原请求')
        raise OutboundDeleteError('删除正在处理或结果待核对；小满单据仍存在，未重复发送删除')

    current = None if missing else remote.read(token, invoice_id)
    if current is not None:
        if str(current.get('company_info', {}).get('id')) != str(record.get('company_id')):
            raise OutboundDeleteError('小满客户归属已变化，请刷新后核对')
        if current.get('status') != 1:
            raise OutboundDeleteError('仅支持删除待出库单；已出库单请在小满处理')
        if not isinstance(current.get('record_list'), list):
            raise OutboundDeleteError('小满明细不完整，未删除')
        if expected_order_id is not None and (not current['record_list'] or any(
                str(row.get('order_id')) != str(expected_order_id) for row in current['record_list'])):
            raise OutboundDeleteError('出库单已关联其他订单，不能随当前订单整张删除')
        if expected_snapshot is not None and current != expected_snapshot:
            raise OutboundDeleteError('出库单资料在确认后变化，请刷新后重新确认删除')
    order_ids = sorted({str(row['order_id']) for row in (current or {}).get('record_list', []) if row.get('order_id')})
    if current is None:
        order_ids = ([str(expected_order_id)] if expected_order_id is not None
                     else sorted(_mirror_order_ids(db, invoice_id)))
    # A replacement/partial live outbound still owns its existing task. Preserve
    # it when retiring an old mirror row for the same order.
    order_ids = [identity for identity in order_ids if identity not in retained_orders]
    # Match the poller's invoice -> task locking order, so a claimed writer wins
    # before our hold or observes skipped after our durable intent commits.
    invoice_ids=[value for (value,) in db.query(Invoice.id).filter(Invoice.xiaoman_order_id.in_(order_ids)).order_by(Invoice.id)]
    db.rollback()
    epochs={identity:legacy_sending.authorize(db,identity).epoch for identity in invoice_ids}
    if not missing:
        _current_delete_actor(db, user_id, record)
    invoices = db.query(Invoice).filter(Invoice.id.in_(invoice_ids)).order_by(Invoice.id).populate_existing().with_for_update().all()
    if current is not None and (not order_ids or {str(row.xiaoman_order_id) for row in invoices}!=set(order_ids)):
        raise OutboundDeleteError('关联原订单缺少完整办理权登记，不能删除')
    event=db.query(ShippingOperationEvent).filter_by(scope=SCOPE,request_id=invoice_id).populate_existing().with_for_update().first()
    if (deepcopy((event.action,event.payload,event.result)) if event else None)!=event_before:
        raise OutboundDeleteError('原删除记录在取证期间变化，请读取原任务')
    from app.shipping_inspection import outbound_sync_state
    for invoice in invoices:
        try:
            outbound_sync_state.ensure_invoice_idle(db, invoice)
        except ValueError as exc:
            raise OutboundDeleteError(str(exc)) from exc
    if any(inv.linked_sync_id for inv in invoices):
        raise OutboundDeleteError('关联订单正在同步，请处理完成后再删除')
    tasks = db.query(OkkiOutboundTask).filter(OkkiOutboundTask.order_id.in_(order_ids)).order_by(OkkiOutboundTask.id).populate_existing().with_for_update().all()
    if task_versions is not None and any(task_versions.get(t.id) != task_version(t) for t in tasks):
        raise OutboundDeleteError('出库任务在核对期间变化，下轮重新核对')
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
                'order_ids': order_ids, 'invoice_ids':invoice_ids,'authority_epochs':epochs,
                'attempt_key':uuid4().hex,'tasks': saved_tasks, 'before': current}
    if event is None:
        event = audit_service.record(db, PENDING, user_id, record['outbound_record_id'],
            context={'scope': SCOPE, 'source': 'scheduler' if missing else 'pc'}, request_id=invoice_id, payload=snapshot)
        if missing:
            event.operator_name = event.login_name = '系统同步'
    else:
        snapshot['previous_attempts'] = [*(event.payload or {}).get('previous_attempts', []),
            {'operator_user_id': event.operator_user_id, 'operator_name': event.operator_name,
             'result': event.result}]
        event.action, event.payload = PENDING, snapshot
        actor = db.get(ArkUser, user_id)
        event.operator_user_id = event.login_user_id = user_id
        event.operator_name = event.login_name = actor.real_name if actor else str(user_id)
        if missing:
            event.source = 'scheduler'
            event.operator_name = event.login_name = '系统同步'
    event.result = {'status': PENDING, 'started_at': str(beijing_now())}
    for task in tasks:
        task.status, task.reason = 'skipped', f'delete_pending:{invoice_id}'
    try:
        _commit(db)  # Durable intent before POST; concurrent inserts lose here.
    except IntegrityError as exc:
        raise OutboundDeleteError('另一请求正在删除这张出库单，请稍后核对') from exc
    if current is None:
        return _finish(db, event, DELETED, '小满出库单已不存在')

    event_id=event.id
    db.rollback()
    for identity in invoice_ids:legacy_sending.authorize(db,identity,epochs[identity])
    _current_delete_actor(db, user_id, record)
    event = db.query(ShippingOperationEvent).filter_by(id=event_id).populate_existing().with_for_update().one()
    if event.action != PENDING or datetime.fromisoformat(event.result['started_at']) + timedelta(minutes=5) <= beijing_now():
        raise OutboundDeleteError('删除执行权已失效，请重新核对原任务')
    tickets=[legacy_sending.start_removal(db,identity,f'legacy:delete-outbound:{invoice_id}:{snapshot["attempt_key"]}:{identity}',
        'outbound',invoice_id,{'actor_id':user_id,'outbound_id':invoice_id,'event_id':event_id,
        'attempt_key':snapshot['attempt_key'],'invoice_ids':invoice_ids,'binding_hash':legacy_sending.ownership.digest(snapshot)},epochs[identity]) for identity in invoice_ids]
    event.payload={**snapshot,'sending_claims':[ticket.request_key for ticket in tickets]}
    _commit(db)
    try:
        remote.remove(token, invoice_id,db=db,ticket=tickets)
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


def abandon_pending(db, record, actor, reason):
    """End the local workflow; preserve any unresolved original HTTP claim."""
    identity=str(record['outbound_invoice_id'])
    if db.new or db.dirty or db.deleted:raise OutboundDeleteError('请先保存后核对原删除任务')
    db.rollback()
    event=db.query(ShippingOperationEvent).filter_by(scope=SCOPE,request_id=identity).first()
    if not event or event.action not in (PENDING,UNCERTAIN):
        raise OutboundDeleteError('没有待恢复的删除任务')
    expected=deepcopy((event.action,event.payload,event.result));event_id=event.id
    stamp=(event.result or {}).get('started_at') or (event.result or {}).get('checked_at')
    if not stamp or datetime.fromisoformat(stamp)+timedelta(minutes=5)>beijing_now():
        raise OutboundDeleteError('原删除任务尚未过期，请至少等待5分钟后核对')
    orders=(event.payload or {}).get('order_ids',[])
    ids=[value for (value,) in db.query(Invoice.id).filter(Invoice.xiaoman_order_id.in_(orders)).order_by(Invoice.id)]
    db.rollback()
    epochs={value:legacy_sending.authorize(db,value).epoch for value in ids}
    db.commit()
    token=ensure_access_token(db);db.commit()
    current=remote.read(token,identity)
    db.rollback()
    for value in ids:legacy_sending.authorize(db,value,epochs[value])
    event=db.query(ShippingOperationEvent).filter_by(id=event_id).populate_existing().with_for_update().one()
    if (event.action,event.payload,event.result)!=expected:
        raise OutboundDeleteError('原删除记录在核对期间变化，请重新读取')
    if current is None:return _finish(db,event,DELETED,'人工核对时确认小满出库单已不存在')
    before=(event.payload or {}).get('before') or {}
    if str(current.get('company_info',{}).get('id'))!=str(before.get('company_info',{}).get('id')):
        raise OutboundDeleteError('小满客户归属已变化，不能恢复原任务')
    event.action='delete_abandoned'
    event.result={'status':'delete_abandoned','message':reason,'operator_id':actor,
        'checked_at':str(beijing_now()),'remote_status':current.get('status')}
    for saved in event.payload.get('tasks',[]):
        task=db.query(OkkiOutboundTask).filter_by(id=saved['id']).with_for_update().first()
        if task and task.reason==f'delete_pending:{identity}':task.reason=f'delete_abandoned:{identity}'
    _commit(db)
    return {'deleted':False,'message':'已保留小满原单并终止本地删除流程；原发送责任继续待核对，不会重发或自动重建'}
