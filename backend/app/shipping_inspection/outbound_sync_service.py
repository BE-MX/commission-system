"""Outbound synchronization with verified, one-row recovery of partial writes."""
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.core.time import beijing_now
from app.invoice import delegation_service, okki_client, xiaoman_service, linked_outbound_service
from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask
from app.invoice.linked_sync_service import edit_version
from app.receipt import remote
from app.shipping_inspection import audit_service, outbound_sync_plan as plans, outbound_sync_state as state
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent

logger = logging.getLogger(__name__)


def commit(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning('Outbound synchronization commit failed')
        print('[outbound_sync] commit failed', flush=True)
        raise


def _read(db, identity):
    result = remote.read(db, '/v1/invoices/outbound/info', {'outbound_invoice_id': identity})
    if (not isinstance(result, dict) or str(result.get('outbound_invoice_id')) != str(identity)
            or not result.get('update_time') or not isinstance(result.get('record_list'), list)
            or any(not isinstance(row, dict) for row in result['record_list'])):
        raise ValueError('小满返回的出库单身份或版本无效')
    return result


def _invoice(db, current, user):
    ids = {str(r.get('order_id') or '') for r in current.get('record_list', [])}
    if len(ids) != 1 or not next(iter(ids)).isdigit():
        raise ValueError('只支持唯一关联一个方舟订单的出库单')
    invoice = db.query(Invoice).options(selectinload(Invoice.items)).filter(
        Invoice.xiaoman_order_id == next(iter(ids))).populate_existing().with_for_update().first()
    if invoice is None:
        raise ValueError('未找到关联的方舟订单发票，不能同步')
    if invoice.order_type == 'presale':
        raise ValueError('预售出库单必须按发货批次核对，禁止整单覆盖')
    _load_items(db, invoice)
    if 'super_admin' not in user.get('roles', []) and 'invoice:read_all' not in user.get('permissions', []):
        if not delegation_service.can_access_invoice(db, int(user['sub']), invoice):
            raise HTTPException(404, '关联发票不存在')
    return invoice


def _load_items(db, invoice):
    # Current reads are essential after waiting for the invoice lock on MySQL RR.
    items = db.query(InvoiceItem).filter_by(invoice_id=invoice.id).order_by(InvoiceItem.sort_order, InvoiceItem.id).populate_existing().with_for_update().all()
    set_committed_value(invoice, 'items', items)


def _idle(db, invoice, record_id):
    if invoice.status in ('cancel_pending', 'cancelled') or invoice.linked_sync_id:
        raise ValueError('订单正在取消或关联同步，请先处理订单任务')
    if invoice.sync_status != 'synced':
        raise ValueError('请先在订单发票中将最新订单同步到小满，再同步出库单')
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).with_for_update().first()
    if task and (task.status in ('running', 'uncertain') or (task.reason or '').startswith('delete_')):
        raise ValueError('关联出库任务正在执行或待处理，请先核对任务')
    deletion = db.query(ShippingOperationEvent).filter_by(scope='outbound-delete', outbound_record_id=record_id).with_for_update().first()
    if deletion and deletion.action != 'delete_failed':
        raise ValueError('该出库单存在删除任务，请先完成删除核对')


def _prepare(db, record, user, *, desired_serial_id=None, number_only=False):
    before = _read(db, record['outbound_invoice_id'])
    if str(before.get('company_info', {}).get('id')) != str(record.get('company_id')):
        raise ValueError('出库单客户归属发生变化，请刷新后核对')
    invoice = _invoice(db, before, user)
    event = state.lock(db, record['outbound_record_id'], int(user['sub']))
    if event.action in state.ACTIVE:
        return invoice, event, None
    _idle(db, invoice, record['outbound_record_id'])
    order = remote.read(db, '/v1/invoices/order/info', {'order_id': invoice.xiaoman_order_id})
    if str(order.get('order_id')) != invoice.xiaoman_order_id:
        raise ValueError('小满订单身份不一致')
    if str(order.get('company_id')) != invoice.customer_id or order.get('currency') != invoice.currency:
        raise ValueError('方舟与小满订单客户或币种不一致')
    related = linked_outbound_service.find_related(db, order)
    if len(related) != 1 or str(related[0]['outbound_invoice_id']) != str(before['outbound_invoice_id']):
        raise ValueError('订单存在分批或多张出库单，请在小满分别核对，不能整单覆盖')
    rows, bindings, issues, _ = xiaoman_service._build_product_rows(db, invoice, xiaoman_service.get_settings_row(db), editing=True)
    if issues or any(len(items) != 1 for items, _ in bindings):
        raise ValueError('订单存在未建品或无法一一对应的明细，请先在订单发票处理')
    live = plans.index(order['product_list'], 'unique_id')
    products = []
    for items, row in bindings:
        item = items[0]
        if str(row.get('unique_id')) not in live:
            raise ValueError('新增产品尚未同步小满订单，请先同步订单发票')
        product = {**live[str(row['unique_id'])], **row, 'product_name': item.product_name}
        products.append(product)
    plan = plans.build(before, order, products, invoice.remark or '', serial_id=desired_serial_id)
    if number_only and (plan['changes'] or plan['remark_changed']):
        raise ValueError('出库单还有明细或备注变化，请由仓库同步并核对，未自动改号')
    if plan['serial_changed']:
        occupant = okki_client.find_outbound_by_serial(db, desired_serial_id)
        if occupant and str(occupant['outbound_invoice_id']) != str(before['outbound_invoice_id']):
            raise ValueError('新出库单号已被其他小满出库单占用，请先核对')
    inspection = db.query(ShippingInspection).filter_by(outbound_record_id=record['outbound_record_id']).with_for_update().populate_existing().first()
    media = db.query(ShippingInspectionPhoto).filter_by(inspection_id=inspection.id).with_for_update().all() if inspection else []
    if (number_only and not plan['serial_changed'] and inspection
            and inspection.outbound_no != before.get('serial_id')):
        raise ValueError('小满出库号已更新，但方舟验货单号尚未核对，请由仓库处理')
    plan['inspection'] = {'id': inspection.id, 'status': inspection.status, 'edit_version': inspection.edit_version,
                          'media_ids': [photo.id for photo in media]} if inspection else None
    plan['requires_recheck'] = bool(plan['material_changed'] and media)
    if plan['requires_recheck']:
        event.action = state.RECHECK
        event.payload = {'invoice_id': invoice.id, 'plan': plan}
        event.result = {**(event.result or {}), 'message': '订单已更新，出库单待仓库同步并重新验货'}
    elif event.action == state.RECHECK:
        event.action = 'sync_idle'
    # Re-read after association scan; never submit a baseline from before a long scan.
    if _read(db, record['outbound_invoice_id']) != before:
        raise ValueError('出库单在核对期间发生变化，请重新预览')
    plan.update(before=before, invoice_id=invoice.id, invoice_no=invoice.invoice_no,
                invoice_version=edit_version(invoice), order=order,
                source_items=[{'unique_id': i.xiaoman_unique_id, 'model': i.model, 'size': i.length, 'color': i.color} for i in invoice.items])
    plan['version'] = plans.digest(plan)
    return invoice, event, plan


def preview(db, record, user, *, desired_serial_id=None, number_only=False):
    invoice, event, plan = _prepare(db, record, user, desired_serial_id=desired_serial_id,
                                    number_only=number_only)
    commit(db)
    if plan is None:
        return {'status': event.action, 'recover': True, 'message': '正在核对上次同步结果，并检查能否安全补齐缺失明细', 'invoice_no': invoice.invoice_no}
    return {k: plan[k] for k in ('version', 'invoice_no', 'changes', 'remark_before', 'remark_after', 'serial_before',
                                  'serial_after', 'serial_changed', 'changed',
                                  'requires_recheck')} | {'inspection_status': (plan['inspection'] or {}).get('status')}


def _snapshot(plan, after):
    source = {str(x['unique_id']): x for x in plan['source_items']}
    items = []
    for row in after['record_list']:
        local = source[str(row['order_record_id'])]
        items.append({'item_id': 'okki:' + str(row['outbound_record_id']), 'product_id': str(row['product_id']),
            'product_name': row['product_name'], 'model': local['model'] or row.get('product_model'),
            'size': local['size'], 'color': local['color'], 'spec': row.get('product_model'),
            'sku': row.get('sku_code'), 'qty': float(row['outbound_count']), 'unit': row['product_unit']})
    return {'update_time': after['update_time'], 'serial_id': after.get('serial_id'),
            'remark': after.get('remark'), 'items': items}


def _verify_finish(db, event):
    plan = event.payload['plan']
    try:
        after = _read(db, plan['before']['outbound_invoice_id'])
        plans.verify(plan['before'], after, plan)
    except (ValueError, KeyError, TypeError, okki_client.OkkiApiError) as exc:
        event.action = 'sync_uncertain'
        event.result = {**(event.result or {}), 'message': str(exc), 'checked_at': str(beijing_now())}
        commit(db)
        return {'status': 'sync_uncertain', 'recover': True, 'message': '同步结果待核对：' + str(exc)}
    recheck = plan.get('inspection')
    previous = event.result or {}
    stale_ids = set(previous.get('stale_media_ids') or [])
    required_ids = set(previous.get('required_recheck_ids') or [])
    if plan.get('material_changed') and recheck:
        inspection = db.query(ShippingInspection).filter_by(id=recheck['id']).with_for_update().populate_existing().first()
        if inspection is None or inspection.edit_version != recheck['edit_version'] or inspection.status != recheck['status']:
            event.action = 'sync_uncertain'
            event.result = {**previous, 'message': '出库已同步，但验货记录发生变化，需人工核对'}
            commit(db)
            return {'status': 'sync_uncertain', 'recover': True, 'message': event.result['message']}
        media = db.query(ShippingInspectionPhoto).filter_by(inspection_id=inspection.id).with_for_update().all()
        if {photo.id for photo in media} != set(recheck['media_ids']):
            event.action = 'sync_uncertain'
            event.result = {**previous, 'message': '出库已同步，但验货媒体发生变化，需人工核对'}
            commit(db)
            return {'status': 'sync_uncertain', 'recover': True, 'message': event.result['message']}
        if plan.get('serial_changed'):
            inspection.outbound_no = after['serial_id']
        if media:
            # Business-mirror item IDs are not guaranteed to equal OKKI outbound_record_id.
            # For changed item sets, invalidate all old evidence and recheck the current mirror rows.
            if plan['material_order_ids'] or plan['removed_order_ids']:
                stale_ids.update(photo.id for photo in media)
                required_ids.add('__all_items__')
            elif plan['remark_changed']:
                stale_ids.update(photo.id for photo in media if photo.item_id is None)
            if plan['requires_whole_recheck']:
                required_ids.add('__whole__')
        inspection.edit_version += 1  # Reject every workstation page opened against the old outbound version.
    event.action = 'sync_done'
    event.result = {'verified': _snapshot(plan, after), 'checked_at': str(beijing_now()),
                    'stale_media_ids': sorted(stale_ids), 'required_recheck_ids': sorted(required_ids),
                    'message': '已同步最新订单资料；请补验变更明细' if required_ids else '已同步最新订单资料，可直接打印'}
    commit(db)
    return {'status': 'sync_done', 'message': event.result['message']}


def _expired(event):
    return datetime.fromisoformat(event.result['started_at']) + timedelta(minutes=5) <= beijing_now()


def _recover(db, event):
    if event.action in ('sync_pending', 'sync_sending') and not _expired(event):
        return {'status': event.action, 'recover': True, 'message': '同步仍在处理中，请稍后核对；不会重复发送'}
    if event.action == 'sync_pending':
        # The sender must acquire this same lock and validate its lease before marking sending.
        event.action = 'sync_failed'
        commit(db)
        return {'status': 'sync_failed', 'requires_preview': True, 'message': '上次任务未发送且已过期，请重新预览'}
    return _verify_finish(db, event)


def _repair_missing(db, record, user, invoice, event):
    """Send one missing row after proving the previous write and all guards are stable."""
    invoice = db.query(Invoice).filter_by(id=invoice.id).populate_existing().with_for_update().one()
    _load_items(db, invoice)
    event = state.lock(db, record['outbound_record_id'], int(user['sub']))
    if event.action != 'sync_uncertain':
        return {'status': event.action, 'recover': event.action in state.ACTIVE,
                'message': (event.result or {}).get('message', '同步状态已变化，请重新核对')}
    plan = event.payload['plan']
    if edit_version(invoice) != plan['invoice_version']:
        return {'status': 'sync_uncertain', 'message': '订单发票已变化，需人工核对'}
    _idle(db, invoice, record['outbound_record_id'])
    order = remote.read(db, '/v1/invoices/order/info', {'order_id': invoice.xiaoman_order_id})
    if (str(order.get('order_id')) != str(plan['order'].get('order_id'))
            or order.get('company_id') != plan['order'].get('company_id')
            or order.get('currency') != plan['order'].get('currency')
            or order.get('product_list') != plan['order'].get('product_list')):
        return {'status': 'sync_uncertain', 'message': '小满订单已变化，需人工核对'}
    related = linked_outbound_service.find_related(db, order)
    if len(related) != 1 or str(related[0]['outbound_invoice_id']) != str(record['outbound_invoice_id']):
        return {'status': 'sync_uncertain', 'message': '订单关联出库单已变化，需人工核对'}
    inspection = db.query(ShippingInspection).filter_by(outbound_record_id=record['outbound_record_id']).with_for_update().populate_existing().first()
    baseline = plan.get('inspection')
    media = db.query(ShippingInspectionPhoto).filter_by(inspection_id=inspection.id).with_for_update().all() if inspection else []
    if (bool(inspection) != bool(baseline) or (baseline and
            (inspection.id != baseline['id'] or inspection.status != baseline['status']
             or inspection.edit_version != baseline['edit_version']
             or {photo.id for photo in media} != set(baseline['media_ids'])))):
        return {'status': 'sync_uncertain', 'message': '验货资料已变化，需人工核对'}
    current = _read(db, record['outbound_invoice_id'])
    try:
        missing = plans.missing_only(plan['before'], current, plan)
    except (ValueError, KeyError, TypeError) as exc:
        return {'status': 'sync_uncertain', 'message': str(exc)}
    last_step = event.payload.get('repair_step')
    if last_step and str(last_step['order_record_id']) in missing:
        return {'status': 'sync_uncertain', 'message': '上次补齐明细尚未在小满出现，需人工核对；不会重复推送'}
    identity = missing[0]
    actual = plans.index(current['record_list'], 'order_record_id')
    expected = plans.index(plan['expected'], 'order_record_id')
    rows = []
    for key, row in expected.items():
        if key in actual:
            rows.append({**row, 'outbound_record_id': actual[key]['outbound_record_id'],
                         'cost_unit_price_rmb': actual[key].get('cost_unit_price_rmb', 0)})
        elif key == identity:
            rows.append(dict(row))
    payload = {'outbound_invoice_id': current['outbound_invoice_id'],
               'handler': [str(x['user_id']) for x in current['handler_info']],
               'remark': plan['remark_after'], 'record_list': rows}
    if not payload['handler']:
        return {'status': 'sync_uncertain', 'message': '小满出库单处理人缺失，需人工核对'}
    token = okki_client.ensure_access_token(db)
    audit_service.record(db, event.action, event.operator_user_id, event.outbound_record_id,
        context={'scope': 'outbound-sync-history', 'source': 'auto_repair'}, request_id=str(uuid4()),
        payload=event.payload, result=event.result)
    step_nonce = str(uuid4())
    event.payload = {**event.payload, 'repair_step': {'order_record_id': identity,
                     'missing_before': len(missing), 'nonce': step_nonce}}
    event.operator_user_id = event.login_user_id = int(user['sub'])
    from app.auth.models import ArkUser
    actor = db.get(ArkUser, int(user['sub']))
    event.operator_name = event.login_name = actor.real_name if actor else str(user['sub'])
    event.result = {**(event.result or {}), 'started_at': str(beijing_now())}
    event.action = 'sync_pending'
    commit(db)

    # The durable pending/sending transition is the same mutex used by normal sync.
    invoice = db.query(Invoice).filter_by(id=invoice.id).populate_existing().with_for_update().one()
    _load_items(db, invoice)
    event = state.lock(db, record['outbound_record_id'], int(user['sub']))
    if (event.action != 'sync_pending' or _expired(event)
            or event.payload.get('repair_step', {}).get('nonce') != step_nonce):
        raise ValueError('补齐执行权已失效，请重新核对')
    event.action = 'sync_sending'
    commit(db)

    invoice = db.query(Invoice).filter_by(id=invoice.id).populate_existing().with_for_update().one()
    _load_items(db, invoice)
    event = state.lock(db, record['outbound_record_id'], int(user['sub']))
    try:
        _idle(db, invoice, record['outbound_record_id'])
        if (event.action != 'sync_sending' or _expired(event)
                or event.payload.get('repair_step', {}).get('nonce') != step_nonce
                or edit_version(invoice) != plan['invoice_version']):
            raise ValueError('补齐前订单发票已变化，请重新核对')
        if _read(db, record['outbound_invoice_id']) != current:
            raise ValueError('补齐前小满出库单已变化，请重新核对')
        fresh_order = remote.read(db, '/v1/invoices/order/info', {'order_id': invoice.xiaoman_order_id})
        if (fresh_order.get('product_list') != order.get('product_list')
                or fresh_order.get('company_id') != order.get('company_id')
                or fresh_order.get('currency') != order.get('currency')):
            raise ValueError('补齐前小满订单已变化，请重新核对')
    except (ValueError, okki_client.OkkiApiError):
        event.action = 'sync_uncertain'
        commit(db)
        raise
    try:
        response = okki_client._post_json('/v1/invoices/outbound/push', token, payload, context='出库单缺失明细补齐')
        if response is None:
            event.action = 'sync_uncertain'
            commit(db)
            return {'status': 'sync_uncertain', 'message': '小满凭证失效，补齐未发送；请重新核对'}
    except okki_client.OkkiApiError:
        logger.warning('Outbound repair response uncertain record=%s order_record=%s', record['outbound_record_id'], identity)
        print(f"[outbound_sync] repair response uncertain record={record['outbound_record_id']} order_record={identity}", flush=True)
    result = _verify_finish(db, event)
    if result['status'] != 'sync_uncertain':
        return result
    try:
        after = _read(db, record['outbound_invoice_id'])
        remaining = plans.missing_only(plan['before'], after, plan)
    except (ValueError, KeyError, TypeError, okki_client.OkkiApiError):
        return result
    if identity not in remaining and len(remaining) < len(missing):
        return {'status': 'sync_uncertain', 'recover': True, 'repairable': True,
                'message': f'已补齐一条明细，正在继续核对剩余 {len(remaining)} 条'}
    return {'status': 'sync_uncertain', 'message': '补齐结果未生效，需人工核对；不会重复推送'}


def synchronize(db, record, user, version, *, check_only=False, confirm_recheck=False,
                desired_serial_id=None, number_only=False, repair=False):
    invoice, event, plan = _prepare(db, record, user, desired_serial_id=desired_serial_id,
                                    number_only=number_only)
    if event.action in state.ACTIVE:
        result = _recover(db, event)
        if repair and not check_only and result['status'] == 'sync_uncertain' and event.action == 'sync_uncertain':
            return _repair_missing(db, record, user, invoice, event)
        return result
    if check_only and plan['changed']:
        return {'status': 'sync_failed', 'requires_preview': True, 'message': '尚未确认同步成功，请重新预览差异'}
    if check_only:
        event.payload = {'invoice_id': invoice.id, 'plan': plan}
        return _verify_finish(db, event)
    if plan['version'] != version:
        raise ValueError('订单或出库单已变化，请重新预览后同步')
    if plan['requires_recheck'] and not confirm_recheck:
        commit(db)
        return {'status': state.RECHECK, 'message': '订单已更新，出库单需要仓库确认“同步并重验”'}
    if plan['requires_recheck'] and plan['inspection']['status'] == 'submitted':
        raise ValueError('验货单已提交，请先撤回验货，再同步并重新验货')
    if not plan['changed']:
        event.payload = {'invoice_id': invoice.id, 'plan': plan}
        return _verify_finish(db, event)
    token = okki_client.ensure_access_token(db)
    if event.payload:
        audit_service.record(db, event.action, event.operator_user_id, event.outbound_record_id,
            context={'scope': 'outbound-sync-history', 'source': 'pc'}, request_id=str(uuid4()),
            payload=event.payload, result=event.result)
    send_nonce = str(uuid4())
    event.action = 'sync_pending'
    event.payload = {'invoice_id': invoice.id, 'plan': plan, 'send_nonce': send_nonce}
    event.operator_user_id = event.login_user_id = int(user['sub'])
    from app.auth.models import ArkUser
    actor = db.get(ArkUser, int(user['sub']))
    event.operator_name = event.login_name = actor.real_name if actor else str(user['sub'])
    # Keep the previous verified overlay until the new request is verified.
    event.result = {**(event.result or {}), 'started_at': str(beijing_now())}
    commit(db)  # Durable intent BEFORE the only external POST.
    invoice = db.query(Invoice).options(selectinload(Invoice.items)).filter_by(id=invoice.id).populate_existing().with_for_update().one()
    _load_items(db, invoice)
    event = state.lock(db, record['outbound_record_id'], int(user['sub']))
    if (event.action != 'sync_pending' or event.payload['plan']['version'] != version
            or event.payload.get('send_nonce') != send_nonce or event.payload.get('repair_step') or _expired(event)):
        raise ValueError('原同步执行权已失效，请重新核对结果')
    event.action = 'sync_sending'
    commit(db)  # Distinguish safely cancellable preparation from potentially sent requests.
    invoice = db.query(Invoice).filter_by(id=invoice.id).populate_existing().with_for_update().one()
    _load_items(db, invoice)
    event = state.lock(db, record['outbound_record_id'], int(user['sub']))
    if (event.action != 'sync_sending' or event.payload['plan']['version'] != version
            or event.payload.get('send_nonce') != send_nonce or event.payload.get('repair_step') or _expired(event)):
        raise ValueError('原同步执行权已失效，请重新核对结果')
    try:
        _idle(db, invoice, record['outbound_record_id'])
        current_inspection = db.query(ShippingInspection).filter_by(outbound_record_id=record['outbound_record_id']).with_for_update().populate_existing().first()
        current_media = db.query(ShippingInspectionPhoto.id).filter_by(inspection_id=current_inspection.id).with_for_update().all() if current_inspection else []
        baseline = plan.get('inspection')
        if (bool(baseline) != bool(current_inspection) or (baseline and
                (current_inspection.edit_version != baseline['edit_version'] or current_inspection.status != baseline['status']
                 or {row.id for row in current_media} != set(baseline['media_ids'])))):
            raise ValueError('验货资料已变化，请重新预览')
        if edit_version(invoice) != plan['invoice_version'] or _read(db, record['outbound_invoice_id']) != plan['before']:
            raise ValueError('发送前订单或出库单发生变化，请重新预览')
        if plan['serial_changed']:
            occupant = okki_client.find_outbound_by_serial(db, plan['serial_after'])
            if occupant and str(occupant['outbound_invoice_id']) != str(record['outbound_invoice_id']):
                raise ValueError('发送前新出库单号已被占用，请重新预览')
        order = remote.read(db, '/v1/invoices/order/info', {'order_id': invoice.xiaoman_order_id})
        if order != plan['order']:
            raise ValueError('发送前小满订单发生变化，请重新预览')
        if _expired(event):
            raise ValueError('核对耗时过长，请重新预览后同步')
    except (ValueError, okki_client.OkkiApiError):
        event.action = 'sync_failed'
        commit(db)
        raise
    try:
        response = okki_client._post_json('/v1/invoices/outbound/push', token, plan['payload'], context='手动同步出库单')
        if response is None:
            # Authentication rejection proves no accepted write. Do not refresh/replay here.
            event.action = 'sync_failed'
            commit(db)
            raise ValueError('小满凭证已过期，请重新预览后同步')
    except okki_client.OkkiApiError:
        logger.warning('Outbound sync response uncertain record=%s', record['outbound_record_id'])
        print(f"[outbound_sync] response uncertain record={record['outbound_record_id']}", flush=True)
    return _verify_finish(db, event)
