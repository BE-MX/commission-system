"""Continue a successful invoice push into its existing outbound workflow."""
import json
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import selectinload

from app.invoice import linked_outbound_service
from app.invoice.linked_sync_service import edit_version
from app.invoice.models import Invoice, OkkiOutboundTask
from app.receipt import remote
from app.shipping_inspection import outbound_service, outbound_sync_service

logger = logging.getLogger(__name__)
DESTINATION_WAREHOUSE_ID = '8193514242746'  # Same warehouse as deploy/okki_outbound_creator.mjs.


def _stock_shortages(db, order):
    needs = defaultdict(Decimal)
    rows = order.get('product_list')
    if not isinstance(rows, list) or not rows:
        raise ValueError('小满订单明细不完整，不能确认缺货状态')
    for row in rows:
        sku = str(row.get('sku_id') or '')
        try:
            quantity = Decimal(str(row['count']))
        except (KeyError, TypeError, InvalidOperation) as exc:
            raise ValueError('小满订单数量无效，不能确认缺货状态') from exc
        if not sku.isdigit() or quantity <= 0 or not quantity.is_finite():
            raise ValueError('小满订单SKU或数量无效，不能确认缺货状态')
        needs[sku] += quantity
    shortages = []
    for sku, required in needs.items():
        data = remote.read(db, '/v1/product/inventory-list',
                           {'sku_id': sku, 'count': 100, 'start_index': 1})
        inventory = data.get('list') if isinstance(data, dict) else None
        count = data.get('count') if isinstance(data, dict) else None
        if not isinstance(inventory, list) or not str(count).isdigit() or int(count) != len(inventory):
            raise ValueError('目标仓库库存列表不完整，不能确认缺货状态')
        matches = [item for item in inventory if str(item.get('sku_id')) == sku
                   and str(item.get('warehouse_id')) == DESTINATION_WAREHOUSE_ID]
        if len(matches) > 1:
            raise ValueError('目标仓库库存重复，不能确认缺货状态')
        available = Decimal(0)
        if matches:
            item = matches[0]
            try:
                available = Decimal(str(item['enable_count']))
                disabled = int(item['disable_flag'])
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise ValueError('目标仓库可用库存无效，不能确认缺货状态') from exc
            if not available.is_finite() or available < 0 or str(item['disable_flag']) not in ('0', '1'):
                raise ValueError('目标仓库可用库存无效，不能确认缺货状态')
            if disabled:
                available = Decimal(0)
        if available < required:
            shortages.append({'sku_id': sku, 'required': float(required), 'available': float(available)})
    return shortages


def run(db, invoice, user):
    """Never create an outbound here: the fenced worker owns that operation."""
    if invoice.sync_status != 'synced' or not invoice.xiaoman_order_id:
        return {'status': 'manual', 'message': '订单尚未完整同步到小满，出库未处理'}
    invoice_version = edit_version(invoice)
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).with_for_update().first()
    if task and task.status == 'running':
        return {'status': 'pending', 'message': '订单已更新，出库任务正在核对中'}
    if task and task.status == 'uncertain':
        return {'status': 'manual', 'message': '出库提交结果待核对，不能自动重发'}

    order = remote.read(db, '/v1/invoices/order/info', {'order_id': invoice.xiaoman_order_id})
    if str(order.get('order_id')) != str(invoice.xiaoman_order_id):
        raise ValueError('小满订单身份不一致，出库未处理')
    related = linked_outbound_service.find_related(db, order)
    if not related:
        if task and task.status == 'pending':
            return {'status': 'pending', 'message': '订单已更新，出库任务将按最新订单及库存核对后生成'}
        if task and task.status == 'skipped' and not (task.reason or '').startswith('existing:'):
            return {'status': 'manual', 'message': task.reason or '该订单不自动生成出库单，请人工核对'}
        if task and task.status == 'waiting_stock':
            shortages = _stock_shortages(db, order)
            fresh_order = remote.read(db, '/v1/invoices/order/info', {'order_id': invoice.xiaoman_order_id})
            if fresh_order != order:
                return {'status': 'manual', 'message': '库存核查期间小满订单发生变化，请重新核对缺货状态'}
            # The live scan may refresh an access token and commit the session;
            # re-lock both rows before changing the queue after a long read.
            current = db.query(Invoice).options(selectinload(Invoice.items)).filter_by(
                id=invoice.id).populate_existing().with_for_update().one()
            task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).populate_existing().with_for_update().one()
            if (current.sync_status != 'synced' or str(current.xiaoman_order_id) != str(order['order_id'])
                    or edit_version(current) != invoice_version):
                return {'status': 'manual', 'message': '核对期间订单发生变化，请重新同步后处理出库'}
            if task.status != 'waiting_stock':
                return {'status': 'pending' if task.status in ('pending', 'running') else 'manual',
                        'message': '出库任务状态已变化，请刷新出库列表核对'}
            if shortages:
                task.reason = 'Insufficient warehouse stock'
                task.last_error = json.dumps({'outcome': 'waiting_stock', 'order_id': str(order['order_id']),
                                              'reason': task.reason, 'shortages': shortages})
                db.commit()
                return {'status': 'waiting_stock', 'message': '订单已更新，目标仓库仍缺货；库存齐全后自动生成',
                        'shortages': shortages}
            # Only the fenced worker may create; wake it for a fresh live check.
            task.status = 'pending'
            task.reason = None
            task.last_error = None
            db.commit()
            return {'status': 'pending', 'message': '订单已更新，当前核查库存已齐；执行端将再次核对并生成出库单'}
        return {'status': 'manual', 'message': '未找到关联出库单；历史或失败任务不会自动重建，请核对出库任务'}
    if len(related) != 1:
        return {'status': 'manual', 'message': '订单关联多张出库单，请分别核对，不能整单覆盖'}
    if 'super_admin' not in user.get('roles', []) and 'shipping_inspection:write' not in user.get('permissions', []):
        return {'status': 'manual', 'message': '订单已同步；当前账号没有出库修改权限，请由仓库同步待出库单'}
    live = related[0]
    from app.shipping_inspection.router import _outbound_scope
    record = outbound_service.get_record_by_outbound_invoice_id(
        db, str(live['outbound_invoice_id']), okki_user_id=_outbound_scope(db, user))
    if record is None:
        return {'status': 'manual', 'message': '小满出库单已存在，方舟镜像尚未更新；镜像到达后可重新核对'}
    if str(record['outbound_invoice_id']) != str(live['outbound_invoice_id']):
        raise ValueError('出库镜像与小满单据身份不一致，出库未处理')
    preview = outbound_sync_service.preview(db, record, user)
    if preview.get('recover'):
        result = outbound_sync_service.synchronize(db, record, user, None, check_only=True)
    elif preview.get('requires_recheck'):
        return {'status': 'manual', 'message': '订单已同步；出库单已有验货资料，请到出库单确认“同步并重验”'
                if preview.get('inspection_status') != 'submitted' else
                '订单已同步；请先撤回已提交验货单，再到出库单确认“同步并重验”'}
    else:
        result = outbound_sync_service.synchronize(db, record, user, preview['version'])
    if result['status'] == 'sync_done':
        return {'status': 'done', 'message': result['message'], 'outbound_invoice_id': str(live['outbound_invoice_id'])}
    return {'status': 'manual', 'message': result.get('message') or '出库同步结果待核对，请在出库单查看'}


def safely_run(db, invoice, user):
    """The remote order is already committed; report downstream failure separately."""
    try:
        return run(db, invoice, user)
    except Exception as exc:  # noqa: BLE001 - order success must remain visible after downstream failure
        db.rollback()
        logger.warning('Invoice outbound follow-up failed invoice=%s: %s', invoice.id, exc)
        print(f'[outbound_followup] failed invoice={invoice.id}: {type(exc).__name__}', flush=True)
        message = str(exc.detail) if hasattr(exc, 'detail') else str(exc) if isinstance(exc, ValueError) else '出库核对未完成，请到出库单核对'
        return {'status': 'manual', 'message': message[:500]}
