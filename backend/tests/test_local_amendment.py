"""Confirmed amendments produce stock and AR deltas without overwriting cash."""
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.invoice.amendment_service import amend
from app.invoice.commerce_schemas import LocalInvoiceAmend
from app.invoice.settlement_models import Receivable
from app.finance.models import FinanceEvent
from app.inventory.models import StockDocument
from tests.test_local_fulfillment import setup_order, allocate, create_batch
from tests.test_finance_local import finance
from tests.test_invoice_commerce import buyer, draft
from tests.test_inventory_local import stock, balance


def amendment(invoice, stock, finance, warehouse, **changes):
    customer, user, _ = finance
    values = draft(customer, user, stock[0], invoice_no=invoice.invoice_no, shipping_fee=2, surcharge_amount=3,
        items=[dict(id=invoice.items[0].id, local_sku_id=stock[0].id, quantity=4, price_per_piece=30)]).model_dump()
    values.update(request_key="amend", expected_version=invoice.commerce_version, warehouse_id=warehouse.id,
                  business_date=date(2026, 10, 3), reason="customer adds one piece")
    values.update(changes)
    return LocalInvoiceAmend(**values)


def test_confirmed_amendment_preserves_receipts_and_posts_ar_difference(db, stock, finance):
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    goods = db.scalar(select(Receivable).where(Receivable.kind == "goods"))
    receipt = allocate(db, invoice, batch, user, goods, 50, "payment")
    body = amendment(invoice, stock, finance, warehouse)
    amend(db, invoice.id, body, user)
    amend(db, invoice.id, body, user)
    assert invoice.total_amount == 125 and invoice.internal_received == 50 and invoice.internal_balance == 75
    assert receipt.amount == 50 and goods.amount == 93 and goods.adjustment_amount == 30 and goods.paid_amount == 50
    assert balance(db, warehouse, stock[0]).reserved == 4 and balance(db, warehouse, stock[0]).on_hand == 10
    assert sum(event.amount for event in db.scalars(select(FinanceEvent).where(FinanceEvent.action == "adjust_receivable"))) == 31


def test_amendment_contract_change_is_not_counted_twice_in_business_amount(db, stock, finance):
    from app.trade.snapshot_service import build_snapshot
    from app.trade.projection_service import project_invoice
    from app.finance.service import adjust_receivable
    from app.finance.schemas import AdjustmentCreate
    invoice, cash, user, warehouse = setup_order(db, stock, finance)
    target = db.scalar(select(Receivable).where(Receivable.kind == 'goods'))
    allocate(db, invoice, cash, user, target, 50, 'fund-amendment')
    amend(db, invoice.id, amendment(invoice, stock, finance, warehouse), user)
    assert Decimal(build_snapshot(db, invoice.id)['amount_original']) == Decimal('122')
    order = project_invoice(db, invoice.id)
    assert order.amount_usd == Decimal('122')
    adjust_receivable(db, target.id, AdjustmentCreate(request_key='independent-commercial-credit',
        invoice_id=invoice.id, expected_version=target.version, amount=Decimal('-10'), business_date=date(2026, 10, 3),
        reason='Independent customer credit after the contract amendment'), user)
    assert Decimal(build_snapshot(db, invoice.id)['amount_original']) == Decimal('112')
    assert project_invoice(db, invoice.id).id == order.id and order.amount_usd == Decimal('112')


def test_failed_rebooking_rolls_back_money_and_previous_reservations(db, stock, finance, monkeypatch):
    import gc
    from app.invoice import amendment_service
    release = amendment_service.release_line
    def release_and_collect(*args, **kwargs):
        result = release(*args, **kwargs)
        gc.collect()
        return result
    monkeypatch.setattr(amendment_service, "release_line", release_and_collect)
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    count = len(db.scalars(select(StockDocument)).all())
    body = amendment(invoice, stock, finance, warehouse,
        items=[dict(id=invoice.items[0].id, local_sku_id=stock[0].id, quantity=11, price_per_piece=30)])
    with pytest.raises(ValueError, match="库存|可用"):
        amend(db, invoice.id, body, user)
    assert invoice.total_amount == 94 and invoice.items[0].quantity == 3 and invoice.commerce_version == 2
    assert balance(db, warehouse, stock[0]).reserved == 3
    assert len(db.scalars(select(StockDocument)).all()) == count
    assert not db.scalars(select(FinanceEvent).where(FinanceEvent.action == "adjust_receivable")).all()


def test_active_shipment_and_historical_line_identity_block_overwrite(db, stock, finance):
    invoice, batch, user, warehouse = setup_order(db, stock, finance)
    body = amendment(invoice, stock, finance, warehouse,
        items=[dict(local_sku_id=stock[0].id, quantity=4, price_per_piece=30)])
    with pytest.raises(ValueError, match="保留原ID"):
        amend(db, invoice.id, body, user)
    create_batch(db, invoice, user, warehouse, 1, "batch")
    with pytest.raises(ValueError, match="取消未履约"):
        amend(db, invoice.id, amendment(invoice, stock, finance, warehouse), user)


def test_cancelled_batch_retains_line_identity_without_inventory_history(db, stock, finance):
    from app.invoice import commerce_service
    from app.invoice.models import InvoiceItem
    from app.invoice.settlement_models import SettlementItem
    from app.invoice.local_fulfillment_schemas import LocalShipmentAction
    from app.invoice import local_fulfillment
    from tests.test_invoice_commerce import action
    customer, user, account = finance
    warehouse = stock[1][0]
    invoice = commerce_service.create_draft(db, draft(customer, user, stock[0], order_type="production"), user)
    commerce_service.confirm(db, invoice.id, action("confirm-production", 1), user)
    old_id = invoice.items[0].id
    row = create_batch(db, invoice, user, warehouse, 1, "cancelled-batch")
    local_fulfillment.act(db, row.id, LocalShipmentAction(request_key="cancel-batch", expected_version=1, reason="cancel"), user, "cancel")
    body = amendment(invoice, stock, finance, warehouse, order_type="production",
        items=[dict(local_sku_id=stock[0].id, quantity=4, price_per_piece=30)])
    with pytest.raises(ValueError, match="保留原ID"):
        amend(db, invoice.id, body, user)
    assert db.get(InvoiceItem, old_id) is not None
    assert db.scalar(select(SettlementItem.invoice_item_id)) == old_id
