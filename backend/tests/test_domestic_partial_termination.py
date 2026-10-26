"""Quantity cancellation preserves concrete identities, money and work history."""
from decimal import Decimal
import pytest
from app.domestic import constants as C, order_service, unit_service, progress_service
from app.domestic.models import DomesticCustomerLedger, DomesticItemUnit
from tests.test_domestic_item_delete import saved_order
from tests.test_domestic_conditional_routing import conditional_route, conditional_order
from tests.test_domestic_delivery import context, complete, ship


def test_partial_cancel_refunds_selected_quantity_and_replay_is_safe(db):
    user, customer, order, items = saved_order(db)
    order_service.terminate_item(db, items[0].id, '取消一件', user.id, qty=1, request_id='cancel-one')
    assert items[0].order_qty == 1 and items[0].status == C.ITEM_PRODUCING
    assert order.total_amount == order.charged_amount == Decimal('150')
    assert customer.balance == 150
    assert order.total_unit_qty == 3
    order_service.terminate_item(db, items[0].id, '取消一件', user.id, qty=1, request_id='cancel-one')
    assert customer.balance == 150 and db.query(DomesticCustomerLedger).count() == 1
    active = unit_service.ensure_item_units(db, items[0])
    assert len(active) == 1
    cancelled = db.query(DomesticItemUnit).filter_by(item_id=items[0].id, status=2).one()
    items[0].order_qty = 2
    unit_service.sync_item_units(db, items[0], 2)
    assert cancelled.status == 2
    assert cancelled.id not in {u.id for u in unit_service.ensure_item_units(db, items[0])}


@pytest.mark.parametrize('qty', [0, -1, 3, True, 1.5])
def test_invalid_quantity_never_refunds(db, qty):
    user, customer, order, items = saved_order(db)
    with pytest.raises(ValueError):
        order_service.terminate_item(db, items[0].id, '取消', user.id, qty=qty, request_id='invalid-qty')
    assert customer.balance == 100 and order.charged_amount == 200


def test_skipped_final_process_completes_item_and_order(db, conditional_order):
    from app.domestic import report_service
    ctx = conditional_order
    for step in ctx.rows:
        report_service.submit_manual_skip(db, item_id=ctx.item.id, progress_id=step.id,
            qty=ctx.item.order_qty, unit_id=None, reason='客户要求全部跳过',
            request_id=f'complete-skip-{step.id}', user_id=ctx.worker.id)
    assert ctx.item.status == C.ITEM_DONE
    from app.domestic.models import DomesticOrder
    assert db.get(DomesticOrder, ctx.item.order_id).status == C.ORDER_DONE


def test_partial_cancel_preserves_work_and_shipped_units(db, context):
    from app.domestic.models import DomesticOrder, DomesticReportLog, DomesticCustomer
    from app.domestic.shipment_service import shipped_unit_ids
    ctx = context
    units, log = complete(db, ctx, 3)
    ship(db, ctx, 2)
    order = db.get(DomesticOrder, ctx.item.order_id)
    order_service.terminate_item(db, ctx.item.id, '取消其余未发货', order.created_by,
        qty=18, request_id='cancel-unshipped')
    assert ctx.item.order_qty == 2 and ctx.item.status == C.ITEM_SHIPPED
    assert order.status == C.ORDER_SHIPPED
    assert order.charged_amount == 200
    assert db.get(DomesticCustomer, order.customer_id).balance == -200
    assert db.get(DomesticReportLog, log.id).report_qty == 3
    assert len(shipped_unit_ids(db, ctx.item.id)) == 2
    assert len(unit_service.ensure_item_units(db, ctx.item)) == 2
    assert not set(ctx.item.termination_records[0]['unit_ids']) & shipped_unit_ids(db, ctx.item.id)
    order_service.terminate_item(db, ctx.item.id, '取消其余未发货', order.created_by,
        qty=18, request_id='cancel-unshipped')
    assert order.charged_amount == 200


def test_refund_failure_rolls_back_quantity_identities_and_audit(db, monkeypatch):
    from app.domestic import balance_service
    user, customer, order, items = saved_order(db)
    unit_service.ensure_item_units(db, items[0]); db.commit()
    def fail(*args, **kwargs):
        raise ValueError('refund unavailable')
    monkeypatch.setattr(balance_service, 'sync_order_finance', fail)
    with pytest.raises(ValueError, match='refund unavailable'):
        order_service.terminate_item(db, items[0].id, '取消一件', user.id, qty=1, request_id='rollback-test')
    assert items[0].order_qty == 2 and not items[0].termination_records
    assert db.query(DomesticItemUnit).filter_by(item_id=items[0].id, status=1).count() == 2
    assert customer.balance == 100


def test_termination_audit_blocks_delete_and_different_replay(db):
    user, customer, order, items = saved_order(db)
    order_service.terminate_item(db, items[0].id, '取消一件', user.id, qty=1, request_id='delete-audit')
    with pytest.raises(ValueError, match='终止记录'):
        order_service.delete_item(db, items[0].id, user.id)
    db.rollback()
    with pytest.raises(ValueError, match='请求号'):
        order_service.terminate_item(db, items[0].id, '不同的原因', user.id, qty=1, request_id='delete-audit')
    assert customer.balance == 150


def test_sparse_unit_codes_are_printable_and_cancelled_codes_stay_inactive(db):
    from app.domestic.router import get_item_unit_qrcodes
    from app.domestic.schemas import OrderItemUpdate
    user, customer, order, items = saved_order(db)
    order_service.terminate_item(db, items[0].id, '取消一件', user.id, qty=1, request_id='sparse-label')
    order_service.update_item(db, items[0].id, OrderItemUpdate(order_qty=2), user.id)
    data = get_item_unit_qrcodes(items[0].id, 1, 3, db, {'sub': str(user.id)})['data']
    assert data['max_unit_no'] == 3 and data['order_qty'] == 2
    assert [u['unit_no'] for u in data['units']] == [1, 3]
    assert order_service.get_order_detail(db, order.id)['items'][0]['max_unit_no'] == 3


def test_cancellation_unit_reads_are_current_reads(db):
    from sqlalchemy import event
    user, _, _, items = saved_order(db)
    unit_service.ensure_item_units(db, items[0]); db.commit()
    reads = []
    def capture(state):
        if state.is_select and 'ark_domestic_item_units' in str(state.statement):
            reads.append(state.statement)
    event.listen(db, 'do_orm_execute', capture)
    try:
        order_service.terminate_item(db, items[0].id, '取消一件', user.id, qty=1, request_id='locked-reads')
    finally:
        event.remove(db, 'do_orm_execute', capture)
    identity_reads = [s for s in reads if len(list(s.selected_columns)) > 3]
    assert identity_reads and all(s._for_update_arg is not None for s in identity_reads)


@pytest.mark.parametrize('mode', ['report', 'skip'])
def test_cancelled_code_cannot_be_reported_or_skipped(db, conditional_order, mode):
    from app.domestic import report_service
    ctx = conditional_order
    order_service.terminate_item(db, ctx.item.id, '取消尾号一件', ctx.worker.id, qty=1, request_id='cancel-code-test')
    cancelled = db.query(DomesticItemUnit).filter_by(item_id=ctx.item.id, status=2).one()
    with pytest.raises(ValueError, match='失效'):
        if mode == 'report':
            report_service.submit_report(db, item_id=ctx.item.id, progress_id=ctx.rows[0].id,
                qty=1, unit_id=cancelled.id, user_id=ctx.worker.id, request_id='cancelled-report')
        else:
            report_service.submit_manual_skip(db, item_id=ctx.item.id, progress_id=ctx.rows[0].id,
                qty=None, unit_id=cancelled.id, reason='主管确认无需加工', user_id=ctx.worker.id, request_id='cancelled-skip')


@pytest.mark.parametrize('utc_hour, expected', [(15, '2026-10-25 23:59:59'), (16, '2026-10-26 00:59:59')])
def test_audit_time_is_beijing_across_midnight_on_non_beijing_host(db, monkeypatch, utc_hour, expected):
    from datetime import datetime, timezone
    from app.core import time
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 25, utc_hour, 59, 59, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setenv('TZ', 'America/New_York')
    monkeypatch.setattr(time, 'datetime', Clock)
    user, _, _, items = saved_order(db)
    order_service.terminate_item(db, items[0].id, '取消一件', user.id, qty=1, request_id='beijing-audit')
    assert items[0].termination_records[0]['terminated_at'] == expected
