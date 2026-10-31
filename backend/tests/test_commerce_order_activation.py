"""A reviewed full order resumes remaining goods/cash on its original identity."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from app.commerce_migration import activation_service as service, inventory_service, fulfillment_service
from app.commerce_migration.activation_schemas import ActivationManifest
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.commerce_migration.fulfillment_schemas import FulfillmentOpeningManifest
from app.finance import service as cash_service
from app.finance.schemas import AllocationCreate
from app.invoice.models import Invoice
from app.invoice.settlement_models import Receivable, ShipmentSettlement, ShipmentOutbound, SettlementApplication
from app.inventory.models import StockBalance, StockLedger
from app.models.commission import SyncedPayment
from app.trade.projection_service import project_invoice
from app.invoice.opening_pricing import quote_remaining
from tests.test_commerce_fulfillment_opening import inputs
from tests.test_inventory_local import stock
from tests.test_finance_local import finance, payment, cmd
from tests.test_invoice_commerce import buyer
from tests.test_local_fulfillment import create_batch, act, inspect

DAY = date(2026, 10, 3)


def prepared(db, stock, finance, *, hand=10):
    raw, invoice, cash, mapping, user = inputs(db, stock, finance, reservations=[dict(warehouse_id=stock[1][0].id, quantity=4)])
    body = ActivationManifest(request_key='enable-source-whole', business_date=DAY,
        orders=[dict(order_binding_record_id=mapping['record_id'], expected_version=invoice.commerce_version)])
    assert not service.preview(db, body)['can_activate']
    fulfillment_service.apply_manifest(db, FulfillmentOpeningManifest.model_validate(raw), user)
    assert not service.preview(db, body)['can_activate']
    opening = InventoryOpeningManifest(batch_key='whole-stock', source='physical-count', tenant='warehouse',
        cutover_date=DAY, evidence_sha256='f'*64, review_reference='Synthetic closing count', materials=[],
        stocks=[dict(external_id='closing-stock', mode='initialize', warehouse_id=stock[1][0].id,
            local_sku_id=invoice.items[0].local_sku_id, quality='sellable', on_hand=hand, reserved=0)])
    inventory_service.apply_manifest(db, opening, user)
    db.commit()
    return body, invoice, cash, mapping, user


def test_whole_activation_then_future_cash_and_dispatch_preserves_original_paid_facts(db, stock, finance):
    body, invoice, cash, mapping, user = prepared(db, stock, finance)
    original = db.scalars(select(SyncedPayment).where(SyncedPayment.payment_id == 'OLD-PAYMENT')).one()
    original_money = (original.payment_amount, original.exchange_rate, original.real_amount_rmb)
    assert service.preview(db, body)['can_activate']
    result = service.activate(db, body, user); db.commit()
    assert invoice.commerce_status == 'partially_shipped' and invoice.items[0].stock_shipped_quantity == 6
    assert invoice.items[0].stock_reserved_quantity == 4
    bucket = db.scalars(select(StockBalance)).one()
    assert bucket.on_hand == 10 and bucket.reserved == 4 and db.scalar(select(func.count()).select_from(StockLedger)) == 2
    assert service.activate(db, body, user) == result
    order = project_invoice(db, invoice.id)
    assert order.id == mapping['customer_order_id'] and order.amount_usd == 1000 and order.external_order_id == 'OLD-ORDER'
    # New cash and future dispatch use ordinary commands with no opening bypass.
    customer, _, bank = finance
    batch = cash_service.register(db, payment(customer, bank, request_key='future-cash', bank_reference='future-cash-ref',
        gross_amount='400', actual_bank_fee=0, collection_date=DAY), user)
    cash_service.confirm(db, batch.id, cmd('future-confirm', batch.version).model_copy(update={'business_date': DAY}), user)
    target = db.get(Receivable, mapping['receivables'][0]['receivable_id'])
    cash_service.allocate(db, batch.id, AllocationCreate(request_key='future-allocate', expected_version=batch.version,
        invoice_id=invoice.id, receivable_id=target.id, amount='400', business_date=DAY), user)
    row = create_batch(db, invoice, user, stock[1][0], 4, 'future-final')
    assert row.quote['goods_amount'] == row.quote['goods_payment_due'] == '400.00'
    act(db, row, user, 'future-ready', 'ready')
    inspection = inspect(db, row, user)
    act(db, row, user, 'future-ship', 'ship', inspection_version=inspection.edit_version); db.commit()
    assert invoice.commerce_status == 'shipped' and invoice.items[0].quantity == invoice.items[0].stock_shipped_quantity == 10
    assert invoice.total_amount == 1000 and invoice.internal_received == 1000 and invoice.internal_balance == 0
    assert bucket.on_hand == 6 and bucket.reserved == 0
    assert (original.payment_amount, original.exchange_rate, original.real_amount_rmb) == original_money
    assert sum(app.effective_amount for app in db.scalars(select(SettlementApplication))) == 1000
    # A replay after new posting never reapplies the historical reservation.
    assert service.activate(db, body, user) == result and bucket.on_hand == 6


def test_activation_shortage_leaves_all_orders_unavailable(db, stock, finance):
    body, invoice, _, _, user = prepared(db, stock, finance, hand=3)
    assert not service.preview(db, body)['can_activate']
    with pytest.raises(ValueError, match='不足'):
        service.activate(db, body, user)
    db.commit()
    assert invoice.commerce_status == 'opening' and invoice.items[0].stock_reserved_quantity == 0
    assert db.scalars(select(StockBalance)).one().reserved == 0


def test_late_activation_failure_rolls_back_status_reservation_and_event_even_if_caller_commits(db, stock, finance, monkeypatch):
    body, invoice, _, _, user = prepared(db, stock, finance)
    original = service.reserve_line
    def fail(*args):
        original(*args)
        raise ValueError('Synthetic failure after real original reservation')
    monkeypatch.setattr(service, 'reserve_line', fail)
    before = db.scalar(select(func.count()).select_from(StockLedger))
    with pytest.raises(ValueError, match='Synthetic'):
        service.activate(db, body, user)
    db.commit()
    assert invoice.commerce_status == 'opening' and invoice.items[0].stock_reserved_quantity == 0
    assert db.scalars(select(StockBalance)).one().reserved == 0
    assert db.scalar(select(func.count()).select_from(StockLedger)) == before


def test_zero_remaining_goods_with_fully_spent_history_can_ship_remaining_pieces():
    line = SimpleNamespace(id=1, quantity=10, stock_shipped_quantity=5, total_price=Decimal('100'))
    invoice = SimpleNamespace(items=[line], internal_accessory=0, surcharge_amount=0, shipping_fee=0, order_type='stock')
    old = SimpleNamespace(quote=dict(opening_record_id=1, items=[dict(invoice_item_id=1, quantity=5, line_amount='100')],
        packaging_amount='0', handling_amount='0', freight_amount='0'))
    quote = quote_remaining(invoice, {1: 5}, [old], freight=0, deposit_remaining=0, deposit_charge_remaining=0)
    assert quote['is_final'] and quote['items'] == [dict(invoice_item_id=1, quantity=5, line_amount='0.00')]
    assert quote['new_payment_due'] == '0.00'
