"""Atomically skip all remaining work, preserving manual audit and real work counts."""
from hashlib import sha256
from app.core.time import beijing_now
from app.domestic import constants as C, progress_service, routing_service, unit_service
from app.domestic.models import DomesticOrder, DomesticOrderItem, DomesticItemProgress, DomesticSkipLog
from app.domestic.report_service import _assert_order_reportable, _validate_manual_skip_input
from app.domestic.shipment_service import shipped_unit_ids


def skip_all(db, order_id, reason, request_id, user_id):
    _, reason, request_id = _validate_manual_skip_input(
        qty=1, unit_id=None, reason=reason, request_id=request_id)
    try:
        order = db.query(DomesticOrder).filter_by(id=order_id).populate_existing().with_for_update().first()
        if not order:
            raise ValueError('订单不存在')
        records = order.skip_all_records or []
        replay = next((r for r in records if r['request_id'] == request_id), None)
        if replay:
            if (replay['reason'], replay['user_id']) != (reason, user_id):
                raise ValueError('该请求号已用于另一笔跳过')
            return {**replay['result'], 'replayed': True}
        _assert_order_reportable(order)
        if order.status not in (C.ORDER_PRODUCING, C.ORDER_DONE, C.ORDER_SHIPPED):
            raise ValueError('当前订单不能跳过工序')
        items = db.query(DomesticOrderItem).filter_by(order_id=order.id).order_by(
            DomesticOrderItem.id,
        ).populate_existing().with_for_update().all()
        count = 0
        for item in items:
            if item.status in (C.ITEM_SHIPPED, C.ITEM_TERMINATED):
                continue
            rows = db.query(DomesticItemProgress).filter_by(item_id=item.id).order_by(
                DomesticItemProgress.step_order,
            ).with_for_update().all()
            if not rows:
                # Never complete an order by silently ignoring an unconfigured item.
                raise ValueError(f'明细 A{item.line_no} 未配工艺路线，请先配置')
            units = unit_service.ensure_item_units(db, item)
            shipped = shipped_unit_ids(db, item.id, lock=True)
            for row in rows:
                key = 'all:' + sha256(f'{order_id}:{request_id}:{row.id}'.encode()).hexdigest()[:60]
                existing = db.query(DomesticSkipLog).filter_by(request_id=key).with_for_update().first()
                if existing and (existing.created_by_user_id != user_id or existing.reason != reason):
                    raise ValueError('该请求号已用于另一笔跳过')
                if existing:
                    continue  # Retrying a revoked operation must never recreate it.
                state = routing_service.load_passage_state(db, item, lock=True)
                eligible = routing_service.eligible_unit_ids(
                    item, row, rows, state, {u.id for u in units},
                    routing_service.runtime_rule_map(db, item.route_id),
                ) - shipped
                selected = [u for u in units if u.id in eligible]
                if not selected:
                    continue
                routing_service.create_skip_log(db, item=item, progress=row, units=selected,
                    source='manual', reason=reason, trigger_report_log_id=None,
                    user_id=user_id, skip_mode='quantity', request_id=key)
                count += len(selected)
            progress_service.sync_progress_statuses(db, item)
            progress_service.recalc_item_status(db, item)
        progress_service.sync_order_status(db, order.id)
        result = {'order_id': order.id, 'status': order.status, 'skipped_qty': count}
        order.skip_all_records = [*records, {
            'request_id': request_id, 'reason': reason, 'user_id': user_id,
            'created_at': beijing_now().isoformat(sep=' ', timespec='seconds'), 'result': result,
        }]
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
