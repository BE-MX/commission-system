"""Cancellation UI facts must agree with the actual isolated financial command."""
from decimal import Decimal

import pytest

from app.invoice import settlement_service as shipments, shipment_state_service
from app.invoice.settlement_models import SettlementApplication
from app.invoice.settlement_schemas import ShipmentQuote
from app.receipt.models import ReceiptLog
from tests.test_presale_runtime import order, payment, create, evidence, USER  # noqa: F401


def test_paused_pool_reservation_can_cancel_and_fund_replacement(db, order):
    receipt = payment(db, order, amount='1000')
    row, _ = create(db, order, freight='0')
    row.state = 'paused'
    db.commit()
    before = {column.name: getattr(receipt, column.name) for column in receipt.__table__.columns}
    public = shipments.describe(db, row)
    assert Decimal(public['balance']['registered_amount']) == Decimal('627')
    assert public['actions']['cancel'] == {'allowed': True, 'reason': ''}
    captured, graph = shipment_state_service._capture(db, order, row.id, 'cancel')
    shipments._change_state_verified(db, captured, USER, 'cancel', row.version, 'Rearrange batch', graph)
    db.commit()
    assert db.query(SettlementApplication).one().status == 'released'
    assert {column.name: getattr(receipt, column.name) for column in receipt.__table__.columns} == before
    assert shipments.describe(db, row)['actions']['cancel']['allowed'] is False
    quote = shipments.build_quote(db, order,
        ShipmentQuote(items=[{'invoice_item_id': order.items[0].id, 'quantity': 3}]), evidence(db, order))
    assert quote['advance_applied'] == '627.00'


@pytest.mark.parametrize('blocker', ['payment', 'receipt_uncertain', 'freight', 'late_result', 'outbound'])
def test_read_cancel_blocker_is_also_enforced_by_command(db, order, blocker):
    from app.invoice.settlement_models import ShipmentOutbound
    receipt = payment(db, order)
    row, _ = create(db, order, freight='0')
    if blocker == 'payment':
        extra = payment(db, order, amount='10', purpose='presale_goods')
        shipments.application(db, row, extra, 'goods', Decimal('10'), Decimal('0'))
    elif blocker == 'receipt_uncertain':
        receipt.sync_status = 'uncertain'
    elif blocker == 'freight':
        target = shipments.target(db, order, row)
        target.remote_order_id, target.remote_status = '300', 'bound'
    elif blocker == 'late_result':
        db.add(ReceiptLog(receipt_id=receipt.id, action='late_result', message='Unresolved original send'))
    else:
        db.add(ShipmentOutbound(settlement_id=row.id, invoice_id=order.id, outbound_no='TEST-OUT',
            payload={}, payload_hash='a'*64))
    db.commit()
    # Some malformed funding graphs intentionally cannot be described. The
    # additional payment uses a partial pool reservation to keep it valid.
    if blocker == 'payment':
        app = db.query(SettlementApplication).filter_by(receipt_id=receipt.id).one()
        app.amount -= Decimal('10')
        quote = dict(row.quote)
        quote['pool_applications'] = [{**part, 'amount': '617.00'} for part in quote['pool_applications']]
        row.quote = quote
        db.commit()
    public = shipments.describe(db, row)
    action = public['actions']['cancel']
    assert action['allowed'] is False and action['reason']
    if blocker == 'outbound':
        graph = shipment_state_service.StateGraph((), {}, None, object())
    else:
        # Current graph capture may reject inconsistent/late evidence before
        # reaching the shared action policy; either path must remain protected.
        try:
            _, graph = shipment_state_service._capture(db, order, row.id, 'cancel')
        except ValueError:
            return
    with pytest.raises(ValueError):
        shipments._change_state_verified(db, row, USER, 'cancel', row.version, 'Cannot cancel', graph)


def test_pause_retains_pool_reservation_and_blocks_new_quote(db, order):
    payment(db, order)
    row, _ = create(db, order, freight='0')
    _, graph = shipment_state_service._capture(db, order, row.id, 'pause')
    shipments._change_state_verified(db, row, USER, 'pause', row.version, 'Temporarily hold', graph)
    db.commit()
    public = shipments.describe(db, row)
    assert public['actions']['pause']['allowed'] is False
    assert public['actions']['resume']['allowed'] is True
    assert db.query(SettlementApplication).one().status == 'reserved'
    with pytest.raises(ValueError, match='活动发货结算'):
        shipments.build_quote(db, order,
            ShipmentQuote(items=[{'invoice_item_id': order.items[0].id, 'quantity': 1}]), evidence(db, order))
