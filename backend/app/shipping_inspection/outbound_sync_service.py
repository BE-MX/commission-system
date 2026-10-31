"""Outbound synchronization with verified, one-row recovery of partial writes."""
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
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


def _prepare(db, record, user, *, desired_serial_id=None, expected_serial_id=None, number_only=False,
             force_authority=False, warehouse=False):
    from app.shipping_inspection import outbound_prepare
    return outbound_prepare.prepare(db, record, user, desired_serial_id=desired_serial_id,
                                     expected_serial_id=expected_serial_id,
                                     number_only=number_only, warehouse=warehouse)


def _prepare_legacy(db, record, user, *, desired_serial_id=None, expected_serial_id=None, number_only=False):
    before = _read(db, record['outbound_invoice_id'])
    if str(before.get('company_info', {}).get('id')) != str(record.get('company_id')):
        raise ValueError('出库单客户归属发生变化，请刷新后核对')
    invoice = _invoice(db, before, user)
    if desired_serial_id is not None and desired_serial_id != invoice.invoice_no:
        raise ValueError('发票号已变化，请重新核对出库单号')
    source_items = [{'unique_id': plans.canonical_identity(i.xiaoman_unique_id),
                     'model': i.model, 'size': i.length, 'color': i.color} for i in invoice.items]
    plans.index(source_items, 'unique_id')
    event = state.lock(db, record['outbound_record_id'], int(user['sub']))
    if event.action in state.ACTIVE:
        return invoice, event, None
    if expected_serial_id is not None and before.get('serial_id') != expected_serial_id:
        raise ValueError('出库单号已变化，请重新核对，未自动改号')
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
    if (not plan['serial_changed'] and inspection and inspection.outbound_no
            and inspection.outbound_no != before.get('serial_id')):
        raise ValueError('小满出库号已更新，但方舟验货单号尚未核对，请由仓库处理')
    plan['inspection'] = {'id': inspection.id, 'status': inspection.status, 'edit_version': inspection.edit_version,
                          'media_ids': [photo.id for photo in media]} if inspection else None
    # Snapshot the old local↔remote row identities before OKKI replaces them, so
    # photos of a deleted-but-recreated product can be inherited by the new row.
    from app.shipping_inspection import outbound_recheck as recheck
    from app.shipping_inspection.outbound_service import item_link_snapshot
    plan['item_links'] = item_link_snapshot(db, record['outbound_record_id'])
    pairs = recheck.carry_pairs({**plan, 'before': before}, {'record_list': plan['expected']},
                                media, plan['item_links'],
                                stale_ids=set((event.result or {}).get('stale_media_ids') or []))
    plan['requires_recheck'] = bool((plan['remark_changed'] or recheck.uncovered(plan, before, pairs)) and media)
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
                source_items=source_items)
    plan['version'] = plans.version_digest(plan)
    return invoice, event, plan


def preview(db, record, user, *, desired_serial_id=None, expected_serial_id=None, number_only=False,
            force_authority=False, warehouse=False):
    enabled = True  # Installed authority is independent of portal rollout.
    try:
        invoice, event, plan = _prepare(db, record, user, desired_serial_id=desired_serial_id,
            expected_serial_id=expected_serial_id,
            number_only=number_only, force_authority=enabled, warehouse=warehouse)
        invoice_id = invoice.id
        if plan is None:
            result = {'status': event.action, 'recover': True,
                      'message': '正在核对上次同步结果，并检查能否安全补齐缺失明细', 'invoice_no': invoice.invoice_no}
        else:
            result = {key: plan[key] for key in ('version', 'invoice_no', 'changes', 'remark_before', 'remark_after',
                'serial_before', 'serial_after', 'serial_changed', 'changed', 'requires_recheck')}
            result['inspection_status'] = (plan['inspection'] or {}).get('status')
        commit(db)
        if enabled:
            from app.shipping_inspection.outbound_prepare import authorize_response
            authorize_response(db, record, user, invoice_id, warehouse)
        return result
    except SQLAlchemyError:
        if not enabled:
            raise
        db.rollback(); db.expire_all()
        logger.warning('Outbound preview commit or response authorization unavailable')
        print('[outbound-sync] preview commit or authorization unavailable', flush=True)
        from app.shipping_inspection.outbound_prepare import reject
        reject(503, '出库预览提交暂不可确认，请读取原任务后重试')


def _snapshot(plan, after):
    source = plans.index(plan['source_items'], 'unique_id')
    items = []
    for row in after['record_list']:
        local = source[plans.canonical_identity(row['order_record_id'])]
        items.append({'item_id': 'okki:' + str(row['outbound_record_id']), 'product_id': str(row['product_id']),
            'sku_id': str(row['sku_id']), 'order_id': str(row['order_id']),
            'order_record_id': str(row['order_record_id']), 'product_cn_name': row.get('product_cn_name') or '',
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
    return _finish_verified(db, event, plan, after)


def _finish_verified(db, event, plan, after, *, commit_result=True, finisher_id=None):
    operator_id = event.operator_user_id if finisher_id is None else finisher_id
    recheck = plan.get('inspection')
    previous = event.result or {}
    stale_ids = set(previous.get('stale_media_ids') or [])
    required_ids = set(previous.get('required_recheck_ids') or [])
    if (plan.get('material_changed') or plan.get('serial_changed')) and recheck:
        inspection = db.query(ShippingInspection).filter_by(id=recheck['id']).with_for_update().populate_existing().first()
        if inspection is None or inspection.edit_version != recheck['edit_version'] or inspection.status != recheck['status']:
            event.action = 'sync_uncertain'
            event.result = {**previous, 'message': '出库已同步，但验货记录发生变化，需人工核对'}
            if commit_result:
                commit(db)
            return {'status': 'sync_uncertain', 'recover': True, 'message': event.result['message']}
        media = db.query(ShippingInspectionPhoto).filter_by(inspection_id=inspection.id).with_for_update().all()
        if {photo.id for photo in media} != set(recheck['media_ids']):
            event.action = 'sync_uncertain'
            event.result = {**previous, 'message': '出库已同步，但验货媒体发生变化，需人工核对'}
            if commit_result:
                commit(db)
            return {'status': 'sync_uncertain', 'recover': True, 'message': event.result['message']}
        inspection.edit_version += 1  # Reject every workstation page opened against the old outbound version.
        if finisher_id is not None:
            inspection.updated_by = finisher_id
        if event.payload.get('auto_recall') and plan['requires_recheck'] and inspection.status == 'submitted':
            inspection.status = 'draft'
            inspection.recalled_at = beijing_now()
            inspection.recalled_by = operator_id
            inspection.updated_at = inspection.recalled_at
            inspection.updated_by = operator_id
            audit_service.record(db, 'recall', operator_id, inspection.outbound_record_id,
                                 inspection=inspection,
                                 context={'source': 'invoice_sync', 'scope': f'invoice_sync:{operator_id}'})
        if plan.get('serial_changed'):
            inspection.outbound_no = after['serial_id']
        if media:
            from app.shipping_inspection.outbound_recheck import carry_media, carry_pairs, changes
            from app.shipping_inspection.outbound_service import inspection_item_links
            links = inspection_item_links(db, inspection.outbound_record_id)
            pairs = carry_pairs(plan, after, media, links, stale_ids=stale_ids)
            # Decide evidence before rebinding: aliases describe the old rows, so the
            # inherited photos must still carry their old local ids here.
            stale, required = changes(plan, after, links, media, previous, pairs=pairs)
            stale_ids, required_ids = set(stale), set(required)
            moved = carry_media(plan, after, links, media, pairs, stale_ids=stale_ids)
            if moved:
                audit_service.record(db, 'media_carry_over', operator_id, inspection.outbound_record_id,
                                     inspection=inspection,
                                     context={'scope': 'outbound-sync-history', 'source': 'invoice_sync'},
                                     payload={'media': moved}, result={'count': len(moved)})
    verified = _snapshot(plan, after)
    from app.invoice.stock_reservations import WAREHOUSE_ID, remember_native
    if str(after.get('invoice_warehouse_info', {}).get('id')) == WAREHOUSE_ID:
        remember_native(db,plan['invoice_id'],plan['order']['order_id'],[after])
    event.action = 'sync_done'
    event.result = {'verified': verified, 'checked_at': str(beijing_now()),
                    'stale_media_ids': sorted(stale_ids), 'required_recheck_ids': sorted(required_ids),
                    'message': '已同步最新订单资料；请补验变更明细' if required_ids else '已同步最新订单资料，可直接打印'}
    if previous.get('verified') == verified and previous.get('print_before_recheck'):
        event.result['print_before_recheck'] = previous['print_before_recheck']
    message = event.result['message']
    if commit_result:
        commit(db)
    return {'status': 'sync_done', 'message': message}


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
    raise ValueError('旧补齐执行入口已停用，请通过当前出库核对入口恢复原任务')


def synchronize(db, record, user, version, *, check_only=False, confirm_recheck=False,
                desired_serial_id=None, expected_serial_id=None, number_only=False, repair=False, auto_recall=False,
                source='pc', force_authority=False, warehouse=False):
    from app.shipping_inspection import outbound_execution
    return outbound_execution.synchronize(db, record, user, version, check_only=check_only,
        confirm_recheck=confirm_recheck, desired_serial_id=desired_serial_id, number_only=number_only,
        expected_serial_id=expected_serial_id, repair=repair, auto_recall=auto_recall,
        source=source, warehouse=warehouse)
