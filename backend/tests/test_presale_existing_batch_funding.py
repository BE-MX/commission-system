"""An edited next batch must not invalidate verified prior shipment funding."""
from copy import deepcopy
from decimal import Decimal

import pytest

from tests.test_presale_runtime import order, evidence
from tests.test_presale_inspection_completion import batch, submit, detail
from app.invoice import shipment_delivery
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.settlement_models import SettlementApplication
from app.receipt.models import Receipt


@pytest.fixture
def existing(db, order, batch, monkeypatch):
    settlement, outbound, inspection = batch
    payload = deepcopy(outbound.payload)
    payload.update(company_id='C1', currency='USD')
    payload['record_list'][0]['sale_price'] = 209
    outbound.payload = payload
    outbound.payload_hash = shipment_delivery.digest(payload)
    submit(db)
    order.total_amount = Decimal('727')  # A new batch, not yet pushed to OKKI.
    order.sync_status = 'not_synced'
    settlement.state, outbound.status = 'outbound_uncertain', 'shipped_unfunded'
    db.commit()
    main = {'order_id':100, 'company_id':'C1', 'currency':'USD', 'amount':627,
        'exchange_rate':700, 'product_list':[{'unique_id':11,'product_id':1,
            'sku_id':2,'count':3,'unit_price':209,'cost_amount':627}]}
    receipts = evidence(db, order)['receipt']['rows']
    live = detail(outbound)
    live['company_info'] = {'id':'C1'}
    def read(_db, path, _params):
        return deepcopy(live if path.endswith('/outbound/info') else main)
    monkeypatch.setattr(shipment_delivery.remote, 'read', read)
    monkeypatch.setattr(shipment_delivery.remote, 'order_active', lambda *_:True)
    monkeypatch.setattr(shipment_delivery.remote, 'order_receipts', lambda *_:deepcopy(receipts))
    monkeypatch.setattr(shipment_delivery.okki_client, 'ensure_access_token', lambda *_:'test')
    monkeypatch.setattr(shipment_delivery.outbound_presence, 'is_active', lambda *_:True)
    monkeypatch.setattr(shipment_delivery, '_refresh_funding', lambda *_:True)
    return settlement, outbound, inspection, main, receipts, live


def test_next_batch_amount_change_does_not_block_original_funded_inspection(db, order, existing):
    settlement, outbound, *_ = existing
    with pytest.raises(ValueError, match='未完成'):
        ensure_mutable(db, order)
    apps = [(a.id, a.amount, a.bank_charge, a.status) for a in db.query(SettlementApplication)]
    assert shipment_delivery.refresh(db, outbound.id) == 'shipped'
    assert settlement.state == 'shipped'
    ensure_mutable(db, order)
    assert order.total_amount == Decimal('727') and order.sync_status == 'not_synced'
    assert [(a.id, a.amount, a.bank_charge, a.status) for a in db.query(SettlementApplication)] == apps


@pytest.mark.parametrize('change', ['customer','currency','deleted','line_missing','line_duplicate',
    'product','sku','quantity','price','amount','missing_amount',
    'receipt_missing','receipt_amount','receipt_currency','receipt_revoked'])
def test_existing_batch_still_blocks_changed_remote_goods_or_cash(db, existing, monkeypatch, change):
    settlement, outbound, _, main, receipts, _ = existing
    if change == 'customer': main['company_id'] = 'another'
    elif change == 'currency': main['currency'] = 'EUR'
    elif change == 'deleted': monkeypatch.setattr(shipment_delivery.remote, 'order_active', lambda *_:False)
    elif change == 'line_missing': main['product_list'] = []
    elif change == 'line_duplicate': main['product_list'] *= 2
    elif change == 'product': main['product_list'][0]['product_id'] = 9
    elif change == 'sku': main['product_list'][0]['sku_id'] = 9
    elif change == 'quantity': main['product_list'][0]['count'] = 0
    elif change == 'price': main['product_list'][0]['unit_price'] = 208
    elif change == 'amount': main['product_list'][0]['cost_amount'] = 600
    elif change == 'missing_amount': main['product_list'][0].pop('cost_amount')
    elif change == 'receipt_missing': receipts.clear()
    elif change == 'receipt_amount': receipts[0]['amount'] = '1'
    elif change == 'receipt_currency': receipts[0]['currency'] = 'EUR'
    elif change == 'receipt_revoked': receipts[0]['collect_status'] = 0
    assert shipment_delivery.refresh(db, outbound.id) == 'shipped_unfunded'
    assert settlement.state == 'outbound_uncertain'


def test_new_batch_creation_keeps_strict_order_amount_check(db, order, existing):
    settlement, *_ = existing
    with pytest.raises(ValueError, match='金额'):
        shipment_delivery._live_funding(db, order, settlement)


@pytest.mark.parametrize('changed', ['inspection','outbound','local_cash'])
def test_unverified_existing_shipment_cannot_use_original_batch_funding(db, existing, changed):
    settlement, outbound, inspection, _, _, live = existing
    if changed == 'inspection': inspection.status = 'draft'
    elif changed == 'outbound': live['record_list'][0]['outbound_count'] = 2
    else: db.query(Receipt).one().collect_status = 0
    db.commit()
    assert shipment_delivery.refresh(db, outbound.id) != 'shipped'
    assert settlement.state != 'shipped'


@pytest.mark.parametrize('change', ['order','application','receipt','payload'])
def test_funding_read_cannot_complete_after_local_changes(db, order, existing, monkeypatch, change):
    _, outbound, _, _, receipts, _ = existing
    def race(*_):
        if change == 'order': order.total_amount += 1
        elif change == 'application': db.query(SettlementApplication).one().amount -= 1
        elif change == 'receipt': db.query(Receipt).one().amount += 1
        else: outbound.payload = {**outbound.payload, 'serial_id':'changed'}
        db.commit()
        return deepcopy(receipts)
    monkeypatch.setattr(shipment_delivery.remote, 'order_receipts', race)
    with pytest.raises(ValueError, match='资金核验期间'):
        shipment_delivery.refresh(db, outbound.id)
    db.expire_all()
    assert outbound.status == 'shipped_unfunded'


@pytest.mark.parametrize('archived_projection', [False, True])
@pytest.mark.parametrize('discounted', [False, True])
def test_partial_archived_batch_accepts_original_or_shipped_projection(db, order, existing, archived_projection, discounted):
    _, outbound, _, main, _, _ = existing
    item = order.items[0]
    item.presale_archived = 1
    item.presale_shipped_quantity = 1
    item.presale_shipped_amount = Decimal('209')
    if discounted:
        # One third rounds to 209.00; reconstructing whole-line cash from the
        # per-batch slice would incorrectly require 627.00 instead of 626.99.
        item.total_price = Decimal('626.99')
        item.discount_amount = Decimal('-.01')
        main['product_list'][0]['cost_amount'] = '626.99'
    if archived_projection:
        main['product_list'][0].update(count=1, cost_amount=209)
    db.commit()
    assert shipment_delivery.refresh(db, outbound.id) == 'shipped'


def test_ambiguous_original_line_cannot_prove_frozen_amount(db, order, existing):
    from app.invoice.models import InvoiceItem
    _, outbound, *_ = existing
    original = order.items[0]
    duplicate = InvoiceItem(**{column.name:getattr(original,column.name) for column in InvoiceItem.__table__.columns
        if column.name not in {'id','created_at','updated_at'}})
    db.add(duplicate);db.commit()
    assert shipment_delivery.refresh(db, outbound.id) == 'shipped_unfunded'
