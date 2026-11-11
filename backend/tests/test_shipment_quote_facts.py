"""Quote changes are economic facts, with independent live reads for each request."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.invoice import shipment_quote_facts as facts, shipment_create_service as create, settlement_service
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_schemas import ShipmentQuote, ShipmentCreate
from app.receipt import remote, receipt_index
from app.receipt.models import Receipt, ReceiptLog
from tests.test_presale_settlement import presale, financial_quote, financial_create, USER


def test_observation_metadata_does_not_invalidate_quote(db, presale, monkeypatch):
    body = ShipmentQuote(items=[{'invoice_item_id': presale.items[0].id, 'quantity': 2}])
    evidence = settlement_service.fetch_evidence(db, presale)
    monkeypatch.setattr(settlement_service, 'fetch_evidence', lambda *_: evidence)
    before = financial_quote(db, presale.id, body, USER)
    evidence['order'].update(update_time='2026-11-11 13:00:00', read_at='later', comment='provider note')
    evidence['receipt']['rows'][0].update(update_time='2026-11-11 13:00:00', amount='3000')
    receipt = db.query(Receipt).one()
    receipt.version += 1
    receipt.synced_at = datetime(2026, 11, 11, 13)
    receipt.attempts = 7
    presale.updated_at = datetime(2026, 11, 11, 14)
    after = financial_quote(db, presale.id, body, USER)
    assert before['quote_hash'] == after['quote_hash']


def test_submission_reports_changed_product_and_preserves_legacy_replay(db, presale):
    draft = ShipmentQuote(items=[{'invoice_item_id': presale.items[0].id, 'quantity': 2}])
    quote = financial_quote(db, presale.id, draft, USER)
    command = ShipmentCreate(**draft.model_dump(), quote_hash=quote['quote_hash'], quote_facts=quote['quote_facts'],
                             request_key='quote_fact_change_001')
    presale.items[0].quantity += 1
    with pytest.raises(ValueError, match='产品行、数量或单价'):
        financial_create(db, presale.id, command, USER)
    presale.items[0].quantity -= 1
    legacy = command.model_copy(update={'quote_facts': None})
    row = financial_create(db, presale.id, legacy, USER)
    assert row.id == financial_create(db, presale.id, legacy, USER).id
    with pytest.raises(Exception, match='409'):
        financial_create(db, presale.id, command, USER)


def test_local_projection_keeps_cash_and_row_binding_but_ignores_readback(db, presale):
    receipt = db.query(Receipt).one()
    models = [(Invoice, [presale]), (InvoiceItem, presale.items), (Receipt, [receipt])]
    before = facts.local_facts(models)
    receipt.version += 1
    receipt.synced_at = datetime(2026, 11, 11)
    receipt.attempts += 1
    assert before == facts.local_facts(models)
    receipt.last_error = 'unverified'
    assert '回款' in facts.changes(before, facts.local_facts(models), local=True)
    receipt.last_error = None
    presale.items[0].xiaoman_unique_id = '99'
    assert '产品行' in facts.changes(before, facts.local_facts(models), local=True)


def test_one_main_detail_and_one_receipt_index_per_evidence_request(monkeypatch):
    target = SimpleNamespace(xiaoman_order_id='100', customer_id='123', currency='USD', total_amount=Decimal('100'), surcharge_amount=0)
    freight = create.FreightTarget(2, 'freight', 'bound', '200', 'Freight', '123', 'USD', Decimal('10'), 1)
    calls = []
    orders = {'100': {'order_id': '100', 'company_id': '123', 'currency': 'USD', 'amount': '100', 'exchange_rate': '7'},
              '200': {'order_id': '200', 'company_id': '123', 'currency': 'USD', 'amount': '10', 'name': 'Freight',
                      'product_total_amount': 0, 'product_list': [], 'exchange_rate': '7'}}
    def read(db, path, params):
        assert path == '/v1/invoices/order/info'
        calls.append(params['order_id'])
        return deepcopy(orders[params['order_id']])
    def receipts(db):
        calls.append('index')
        return [{'cash_collection_id': '1', 'order_id': '100', 'currency': 'USD', 'amount': '10', 'collect_status': 1},
                {'cash_collection_id': '2', 'order_id': '200', 'currency': 'USD', 'amount': '10', 'collect_status': 1}]
    monkeypatch.setattr(remote, 'read', read)
    monkeypatch.setattr(remote, 'order_active', lambda *_: True)
    monkeypatch.setattr(receipt_index, 'verified_rows', receipts)
    monkeypatch.setattr(create.shipment_outbound_evidence, 'find_related', lambda *_: [])
    for _ in range(2):
        evidence = create._evidence(None, target, ((2, freight),))
        assert len(evidence['receipt']['rows']) == len(evidence['freight'][2]['rows']) == 1
    assert calls == ['100', 'index', '200'] * 2
    orders['200']['company_id'] = '999'
    with pytest.raises(ValueError, match='运费订单身份'):
        create._evidence(None, target, ((2, freight),))


def test_credit_effective_is_a_funding_fact_and_positional_bindings_keep_order():
    log = SimpleNamespace(id=1, receipt_id=2, action='synced', message='observed')
    before = facts.local_facts([(ReceiptLog, [log])])
    log.action = 'credit_effective'
    assert '回款' in facts.changes(before, facts.local_facts([(ReceiptLog, [log])]), local=True)
    assert facts.digest({'binding': [1, '2', '10', 'USD', '3', 1]}) != facts.digest(
        {'binding': [1, '3', '10', 'USD', '2', 1]})


@pytest.mark.parametrize('category', ['exchange_rates', 'funding', 'outbounds', 'freight'])
def test_remote_business_changes_are_distinguished(db, presale, category):
    quote = {'pool_balances': {}, 'pool_applications': []}
    evidence = settlement_service.fetch_evidence(db, presale)
    evidence['freight'] = {1: {'rows': [], 'target_binding': [1, '20', '10', 'USD', '3', 1]}}
    evidence['outbounds'] = [{'outbound_invoice_id': '30', 'status': '1', 'company_info': {'id': '3'},
                              'record_list': [{'order_record_id': '11', 'outbound_count': 1}]}]
    before = facts.quote_facts(presale, quote, [], evidence, [])
    if category == 'exchange_rates':
        evidence['order']['exchange_rate'] = '7.2'
    elif category == 'funding':
        evidence['receipt']['rows'][0]['collect_status'] = 0
    elif category == 'outbounds':
        evidence['outbounds'][0]['record_list'][0]['outbound_count'] = 2
    else:
        evidence['freight'][1]['target_binding'][2] = '11'
    after = facts.quote_facts(presale, quote, [], evidence, [])
    assert [key for key in before if before[key] != after[key]] == [category]


def test_new_fact_command_replays_exactly_and_tampering_does_not_bypass_hash(db, presale):
    draft = ShipmentQuote(items=[{'invoice_item_id': presale.items[0].id, 'quantity': 2}])
    quote = financial_quote(db, presale.id, draft, USER)
    command = ShipmentCreate(**draft.model_dump(), quote_hash=quote['quote_hash'], quote_facts=quote['quote_facts'],
                             request_key='quote_fact_replay_001')
    bad = command.model_copy(update={'quote_hash': 'a' * 64, 'quote_facts': {}})
    with pytest.raises(ValueError, match='QUOTE_STALE'):
        financial_create(db, presale.id, bad, USER)
    row = financial_create(db, presale.id, command, USER)
    assert financial_create(db, presale.id, command, USER).id == row.id


@pytest.mark.parametrize('field', ['invoice_id', 'customer_id', 'currency'])
def test_original_replay_rejects_moved_pool_funding(db, presale, field):
    from fastapi import HTTPException
    from app.invoice.settlement_models import ShipmentSettlement, SettlementApplication
    draft = ShipmentQuote(items=[{'invoice_item_id': presale.items[0].id, 'quantity': 10}], is_final=True)
    quote = financial_quote(db, presale.id, draft, USER)
    command = ShipmentCreate(**draft.model_dump(), quote_hash=quote['quote_hash'], quote_facts=quote['quote_facts'],
                             request_key='pool_original_binding_001')
    row = financial_create(db, presale.id, command, USER)
    assert financial_create(db, presale.id, command, USER).id == row.id
    receipt = db.query(Receipt).one()
    if field == 'invoice_id':
        other = Invoice(invoice_no='OTHER-POOL', customer_id=presale.customer_id, customer_name='Other',
                        sales_user_id=1, invoice_date=presale.invoice_date, currency='USD')
        db.add(other); db.flush()
        receipt.invoice_id = other.id
    else:
        setattr(receipt, field, 'other-customer' if field == 'customer_id' else 'CNY')
    with pytest.raises(HTTPException, match='回款所属订单、客户或币种') as error:
        financial_create(db, presale.id, command, USER)
    assert error.value.status_code == 409
    assert db.query(ShipmentSettlement).count() == db.query(SettlementApplication).count() == 1
