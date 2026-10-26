"""Quantity cancellation under the existing order -> item -> customer locks."""
from app.core.time import beijing_now
from app.domestic import constants as C, balance_service, progress_service, unit_service
from app.domestic.shipment_service import shipped_unit_ids


def terminate_item(db, item_id, reason, user_id, *, qty=None, request_id=None):
    from app.domestic.order_service import _lock_order_then_item, _ensure_order_creator
    db.info['domestic_actor_id'] = user_id
    try:
        order, item = _lock_order_then_item(db, item_id)
        _ensure_order_creator(order, user_id)
        reason = (reason or '').strip()
        if not reason or len(reason) > 500:
            raise ValueError('请填写 1 到 500 字的终止原因')
        if qty is not None and (type(qty) is not int or qty <= 0):
            raise ValueError('终止数量必须是正整数')
        if qty is not None and (not request_id or not 8 <= len(request_id) <= 64):
            raise ValueError('按数量终止必须提供 8 到 64 字符请求号')
        records = item.termination_records or []
        replay = next((r for r in records if request_id and r['request_id'] == request_id), None)
        if replay:
            if (replay['requested_qty'], replay['reason'], replay['user_id']) != (qty, reason, user_id):
                raise ValueError('该请求号已用于另一笔终止，请刷新后重试')
            return item
        if item.status == C.ITEM_TERMINATED:
            raise ValueError('该明细已终止')
        if order.status not in (C.ORDER_PRODUCING, C.ORDER_DONE):
            raise ValueError('只有生产中或已完工订单可以终止明细')
        shipped = shipped_unit_ids(db, item.id, lock=True)
        if item.status == C.ITEM_SHIPPED or (qty is None and shipped):
            raise ValueError('该明细已有发货，不能终止整行')
        units = unit_service.ensure_item_units(db, item)
        available = [u for u in reversed(units) if u.id not in shipped]
        quantity = item.order_qty if qty is None else qty
        if quantity > len(available):
            raise ValueError(f'当前最多可终止 {len(available)} 件')
        selected = available[:quantity]
        full = quantity == item.order_qty
        if full:
            # Whole-line termination retains the original line and all work history.
            item.status = C.ITEM_TERMINATED
        else:
            for unit in selected:
                unit.status = 2
            item.order_qty -= quantity
            order.total_unit_qty = max(0, int(order.total_unit_qty or 0) - quantity)
            db.flush()
            progress_service.sync_progress_statuses(db, item)
            progress_service.recalc_item_status(db, item)
            if shipped and len(shipped) == item.order_qty:
                item.status = C.ITEM_SHIPPED
        item.termination_records = [*records, {
            'qty': quantity, 'requested_qty': qty, 'unit_ids': [u.id for u in selected],
            'unit_codes': [unit_service.unit_display_code(item, u.unit_no) for u in selected],
            'reason': reason, 'user_id': user_id, 'request_id': request_id,
            'terminated_at': beijing_now().isoformat(sep=' ', timespec='seconds'),
        }]
        item.remark = f'[终止 {quantity} 件] {reason}\n{item.remark or ""}'.strip()[:2000]
        db.flush()
        balance_service.sync_order_finance(db, order, user_id=user_id,
            reason=f'订单 {order.domestic_no} 明细 A{item.line_no} 终止 {quantity} 件退款：{reason}'[:500])
        progress_service.sync_order_status(db, order.id)
        db.commit()
        return item
    except Exception:
        db.rollback()
        raise
