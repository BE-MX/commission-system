"""Receipt source recovery uses isolated SQLite and deterministic provider evidence."""
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.core.database import get_db
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.okki_client import OkkiApiError
from app.receipt.models import Receipt
from app.sales_return import receipt_sources, schemas, service, sources
from app.sales_return.models import ReturnAllocation, SalesReturn
from app.sales_return.router import router
from tests.test_sales_return_sources import source_db, USER  # noqa: F401


def remote_detail():
    return {'cash_collection_id': 'PAY-1', 'order_id': '101', 'company_id': 'C1',
            'collect_status': 1, 'enable_flag': 1, 'currency': 'USD',
            'amount': '82.00', 'amount_usd': '82.00', 'real_amount': '81.00',
            'real_amount_usd': '81.00', 'bank_charge': '1.00', 'bank_charge_usd': '1.00',
            'collection_date': '2026-10-10',
            'order_info': {'order_id': '101', 'currency': 'USD', 'service_fee_amount_usd': 0}}


@pytest.fixture
def missing_fee_db(source_db):
    source_db.execute(text('UPDATE lsordertest.okki_receipts SET service_fee_amount_usd=NULL'))
    source_db.commit()
    return source_db


def local_receipt(db, *, status='remote_deleted', identity='PAY-OLD'):
    invoice = Invoice(invoice_no='Return source PI', invoice_date=date(2026, 10, 1),
        customer_id='C1', customer_name='Test Company', currency='USD', sales_user_id=7,
        xiaoman_order_id='101', status='synced', sync_status='synced')
    invoice.items.append(InvoiceItem(product_name='Hair', product_display='Hair', color='Black',
        product_id='P1', sku_id='S1', quantity=4, total_price=100, xiaoman_unique_id='REMOTE-ORDER-LINE'))
    db.add(invoice)
    db.flush()
    row = Receipt(receipt_no='LOCAL-RECEIPT', invoice_id=invoice.id, source='manual',
        request_key='local-receipt-key', request_hash='local-hash', amount=82, bank_charge=1,
        currency='USD', customer_id='C1', collection_date=date(2026, 10, 10), payment_type='bank',
        xiaoman_order_id='101', xiaoman_receipt_id=identity, status=status, sync_status='synced', created_by=7)
    db.add(row)
    db.flush()
    return row


def add_old_mirror(db):
    db.execute(text("""INSERT INTO lsordertest.okki_receipts
        SELECT 'PAY-OLD',order_id,company_id,amount_usd,NULL,collection_date,collect_status,currency,
            amount,service_fee_amount,real_amount,real_amount_usd,bank_charge,bank_charge_usd
        FROM lsordertest.okki_receipts WHERE cash_collection_id='PAY-1'"""))


def payments(db, evidence=None):
    order = sources.order_row(db, '101', USER)
    return sources._payments(db, order, 'USD', evidence)


def test_missing_fee_uses_explicit_nested_zero_without_bank_fee_inference(missing_fee_db, monkeypatch):
    db = missing_fee_db
    calls = []
    def info(session, identity):
        assert not session.in_transaction()
        calls.append(identity)
        return remote_detail()
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', info)
    evidence = receipt_sources.prepare(db, USER, order_id='101')
    result = payments(db, evidence)
    assert calls == ['PAY-1']
    assert result[0]['service_fee_usd'] == '0.00'
    assert result[0]['bank_charge_usd'] == '1.00'
    assert result[0]['principal'] == '81.00'
    assert db.scalar(text('SELECT service_fee_amount_usd FROM lsordertest.okki_receipts')) is None


@pytest.mark.parametrize('value', [None, '', '-1', 'NaN', 'Infinity', 'bad'])
def test_unknown_or_invalid_nested_fee_still_blocks(missing_fee_db, monkeypatch, value):
    detail = remote_detail()
    detail['order_info']['service_fee_amount_usd'] = value
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda *_: detail)
    evidence = receipt_sources.prepare(missing_fee_db, USER, order_id='101')
    with pytest.raises(HTTPException, match='手续费'):
        payments(missing_fee_db, evidence)


def test_nonzero_nested_service_fee_is_deducted_separately(missing_fee_db, monkeypatch):
    detail = remote_detail()
    detail['order_info']['service_fee_amount_usd'] = '2.00'
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda *_: detail)
    evidence = receipt_sources.prepare(missing_fee_db, USER, order_id='101')
    result = payments(missing_fee_db, evidence)[0]
    assert result['principal'] == '79.00' and result['commission_basis_usd'] == '80.00'


@pytest.mark.parametrize('key,value', [('order_id', 'OTHER'), ('company_id', 'OTHER'),
    ('cash_collection_id', 'OTHER'), ('currency', 'EUR'), ('collect_status', 0),
    ('enable_flag', 0), ('enable_flag', None), ('amount', '83'), ('real_amount', None),
    ('bank_charge_usd', '2'), ('collection_date', '2026-10-11'), ('order_info', None),
    ('order_info', {'order_id': 'OTHER', 'currency': 'USD', 'service_fee_amount_usd': 0})])
def test_remote_conflicts_never_produce_a_refund(missing_fee_db, monkeypatch, key, value):
    detail = {**remote_detail(), key: value}
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda *_: detail)
    evidence = receipt_sources.prepare(missing_fee_db, USER, order_id='101')
    with pytest.raises(HTTPException) as error:
        payments(missing_fee_db, evidence)
    assert error.value.status_code == 409


def test_deleted_receipt_is_excluded_before_fee_validation(missing_fee_db, monkeypatch):
    db = missing_fee_db
    add_old_mirror(db)
    local_receipt(db)
    db.commit()
    calls = []
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda _, identity:
        (calls.append(identity), remote_detail())[1])
    evidence = receipt_sources.prepare(db, USER, order_id='101')
    assert calls == ['PAY-1']
    assert [row['payment_id'] for row in payments(db, evidence)] == ['PAY-1']
    assert db.scalar(text('SELECT count(*) FROM lsordertest.okki_receipts')) == 2


@pytest.mark.parametrize('key,value', [('xiaoman_order_id', 'OTHER'), ('customer_id', 'OTHER'),
    ('currency', 'EUR'), ('sync_status', 'uncertain'), ('status', 'voided')])
def test_deleted_receipt_binding_must_be_exact(missing_fee_db, key, value):
    db = missing_fee_db
    add_old_mirror(db)
    row = local_receipt(db)
    setattr(row, key, value)
    db.commit()
    with pytest.raises(HTTPException):
        receipt_sources.prepare(db, USER, order_id='101')


@pytest.mark.parametrize('change', ['amount', 'fee', 'new_row', 'deleted_status'])
def test_remote_evidence_cannot_outlive_source_changes(missing_fee_db, monkeypatch, change):
    db = missing_fee_db
    add_old_mirror(db)
    row = local_receipt(db)
    local_id = row.id
    db.commit()
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda *_: remote_detail())
    evidence = receipt_sources.prepare(db, USER, order_id='101')
    if change == 'amount':
        db.execute(text("UPDATE lsordertest.okki_receipts SET amount=83 WHERE cash_collection_id='PAY-1'"))
    elif change == 'fee':
        db.execute(text("UPDATE lsordertest.okki_receipts SET service_fee_amount_usd=1 WHERE cash_collection_id='PAY-1'"))
    elif change == 'new_row':
        db.execute(text("INSERT INTO lsordertest.okki_receipts SELECT 'PAY-NEW',order_id,company_id,amount_usd,service_fee_amount_usd,collection_date,collect_status,currency,amount,service_fee_amount,real_amount,real_amount_usd,bank_charge,bank_charge_usd FROM lsordertest.okki_receipts WHERE cash_collection_id='PAY-1'"))
    else:
        db.get(Receipt, local_id).status = 'active'
    db.commit()
    with pytest.raises(HTTPException, match='取证期间'):
        payments(db, evidence)


def test_known_mirror_fee_needs_no_remote_request(source_db, monkeypatch):
    source_db.commit()
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda *_: pytest.fail('unexpected remote read'))
    assert receipt_sources.prepare(source_db, USER, order_id='101') is None
    assert payments(source_db)[0]['service_fee_usd'] == '2.00'


def test_order_scope_checked_before_remote_request(missing_fee_db, monkeypatch):
    db = missing_fee_db
    db.execute(text("UPDATE lsordertest.okki_orders SET user_id='OTHER'"))
    db.commit()
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda *_: pytest.fail('unauthorized remote read'))
    with pytest.raises(HTTPException) as error:
        receipt_sources.prepare(db, USER, order_id='101')
    assert error.value.status_code == 404


def test_dirty_business_state_is_not_committed_to_refresh_token(missing_fee_db):
    db = missing_fee_db
    row = local_receipt(db)
    db.commit()
    row.status = 'active'
    with pytest.raises(HTTPException, match='业务写入前'):
        receipt_sources.prepare(db, USER, order_id='101')
    db.rollback()
    assert db.get(Receipt, row.id).status == 'remote_deleted'


def test_provider_failure_is_controlled_and_creates_no_business_rows(missing_fee_db, monkeypatch):
    db = missing_fee_db
    def unavailable(*_):
        raise OkkiApiError('provider unavailable')
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', unavailable)
    with pytest.raises(HTTPException) as error:
        receipt_sources.prepare(db, USER, order_id='101')
    assert error.value.status_code == 503
    assert not db.in_transaction()
    assert db.scalars(select(SalesReturn)).all() == []
    assert db.scalar(text('SELECT service_fee_amount_usd FROM lsordertest.okki_receipts')) is None


@pytest.fixture
def fee_stock_db(source_db):
    row = local_receipt(source_db, status='active', identity='PAY-1')
    invoice = source_db.get(Invoice, row.invoice_id)
    invoice.product_amount = Decimal('570.00')
    invoice.shipping_fee = Decimal('48.11')
    invoice.surcharge_amount = Decimal('30.91')
    invoice.total_amount = Decimal('649.02')
    row.amount, row.bank_charge = Decimal('649.02'), Decimal(0)
    source_db.execute(text("UPDATE lsordertest.okki_receipts SET amount=649.02,amount_usd=649.02,real_amount=649.02,real_amount_usd=649.02,bank_charge=0,bank_charge_usd=0,service_fee_amount_usd=0"))
    source_db.commit()
    return source_db, invoice, row


def goods_payments(db, invoice):
    return sources._payments(db, sources.order_row(db, '101', USER), 'USD', invoice=invoice, goods=Decimal('570'))


@pytest.mark.parametrize('charge,net,non_goods', [('0', '649.02', '79.02'), ('30.91', '618.11', '48.11')])
def test_26008_cash_is_split_from_proven_non_goods_fees(fee_stock_db, charge, net, non_goods):
    db, invoice, row = fee_stock_db
    row.bank_charge = Decimal(charge)
    db.execute(text('UPDATE lsordertest.okki_receipts SET amount=:net,amount_usd=:net,real_amount=:net,real_amount_usd=:net'), {'net': net})
    db.commit()
    result = goods_payments(db, invoice)[0]
    assert result['principal'] == result['principal_usd'] == '570.00'
    assert result['cash_principal'] == result['commission_basis_usd'] == net
    assert result['non_goods_amount'] == non_goods


def test_26008_full_goods_draft_keeps_fees_out_of_refund(fee_stock_db):
    db, invoice, _ = fee_stock_db
    item = invoice.items[0]
    item.quantity, item.total_price = 300, Decimal('570')
    db.execute(text('UPDATE lsordertest.okki_orders SET amount_usd=570'))
    db.execute(text('UPDATE lsordertest.okki_outbound_records SET product_total_amount=570,product_total_amount_usd=570'))
    db.execute(text('UPDATE lsordertest.okki_outbound_record_items SET outbound_count=300,sale_count=300,sale_price=1.9,product_amount=570'))
    db.commit()
    body = schemas.Create(order_id='101', return_type='return_refund', reason_code='quality',
        reason='Verified goods-only return', request_key='full-goods-receipt-source',
        lines=[schemas.Line(source_key='OUT-1:REMOTE-LINE', quantity=300, reduction_amount='570.00')])
    draft = service.create(db, body, USER)
    assert draft.status == 'draft'
    assert draft.refund_amount == draft.reduction_amount == Decimal('570.00')
    payment = draft.snapshot['payments'][0]
    assert payment['cash_principal'] == '649.02'
    assert payment['non_goods_amount'] == '79.02'
    assert payment['commission_basis_usd'] == '649.02'


@pytest.mark.parametrize('change', ['partial', 'excess_charge', 'wrong_product', 'wrong_total',
    'mirror_amount', 'uncertain', 'pending_receipt', 'multiple_mirror', 'extra_service_fee', 'foreign_currency'])
def test_unproven_fee_split_is_never_capped_to_goods(fee_stock_db, change):
    db, invoice, row = fee_stock_db
    if change == 'partial':
        row.amount = Decimal('600')
    elif change == 'excess_charge':
        row.bank_charge = Decimal('31')
    elif change == 'wrong_product':
        invoice.product_amount = Decimal('569')
    elif change == 'wrong_total':
        invoice.total_amount = Decimal('650')
    elif change == 'mirror_amount':
        db.execute(text('UPDATE lsordertest.okki_receipts SET amount=650,real_amount=650,amount_usd=650,real_amount_usd=650'))
    elif change == 'uncertain':
        row.sync_status = 'uncertain'
    elif change == 'pending_receipt':
        db.add(Receipt(receipt_no='PENDING', invoice_id=invoice.id, source='manual', request_key='pending-source',
            request_hash='h', amount=1, bank_charge=0, currency='USD', collection_date=date(2026, 10, 10),
            payment_type='bank', customer_id='C1', xiaoman_order_id='101', created_by=7, status='active', sync_status='pending'))
    elif change == 'multiple_mirror':
        add_old_mirror(db)
        db.execute(text("UPDATE lsordertest.okki_receipts SET service_fee_amount_usd=0 WHERE cash_collection_id='PAY-OLD'"))
    elif change == 'extra_service_fee':
        db.execute(text('UPDATE lsordertest.okki_receipts SET service_fee_amount_usd=2'))
    else:
        invoice.currency = 'EUR'
    db.commit()
    with pytest.raises(HTTPException):
        goods_payments(db, invoice)


def test_http_lines_preview_create_update_activate_and_idempotent_replay(missing_fee_db, monkeypatch):
    db = missing_fee_db
    permissions = ['sales_return:read', 'sales_return:write']
    role = ArkRole(name='receipt_return_test', label='Test')
    role.permissions = [ArkPermission(code=code, module='sales_return', action=code.split(':')[1], label=code)
                        for code in permissions]
    db.add(ArkUser(id=7, username='return-source-test', password_hash='test-only', real_name='Test', roles=[role]))
    add_old_mirror(db)
    local_receipt(db)
    db.commit()
    calls = []
    def info(_, identity):
        calls.append(identity)
        return remote_detail()
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', info)
    user = {**USER, 'permissions': permissions}
    app = FastAPI()
    app.include_router(router, prefix='/api/sales-returns')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    lines = client.get('/api/sales-returns/orders/101/lines')
    assert lines.status_code == 200, lines.text
    assert [row['payment_id'] for row in lines.json()['data']['payments']] == ['PAY-1']
    body = dict(order_id='101', return_type='return_refund', reason_code='quality', reason='Verified quality return',
        lines=[dict(source_key='OUT-1:REMOTE-LINE', quantity=2, reduction_amount='50.00')])
    preview = client.post('/api/sales-returns/preview', json=body)
    assert preview.status_code == 200, preview.text
    quote = preview.json()['data']
    assert quote['refund_amount'] == '50.00'
    create = {**body, 'request_key': 'receipt-source-create-key'}
    created = client.post('/api/sales-returns', json=create)
    assert created.status_code == 200, created.text
    document = created.json()['data']
    identity = document['id']
    updated = client.put(f'/api/sales-returns/{identity}', json={**body, 'version': document['version']})
    assert updated.status_code == 200, updated.text
    command = {'version': updated.json()['data']['version'], 'quote_version': quote['quote_version'],
               'request_key': 'receipt-source-activate-key'}
    activated = client.post(f'/api/sales-returns/{identity}/activate', json=command)
    assert activated.status_code == 200, activated.text
    assert activated.json()['data']['status'] == 'effective'
    assert calls == ['PAY-1'] * 5
    monkeypatch.setattr(receipt_sources.remote, 'receipt_info', lambda *_: pytest.fail('replay must not need remote'))
    replay = client.post('/api/sales-returns', json=create)
    assert replay.status_code == 200 and replay.json()['data']['id'] == identity
    replay = client.post(f'/api/sales-returns/{identity}/activate', json=command)
    assert replay.status_code == 200 and replay.json()['data']['id'] == identity
    assert db.scalar(select(ReturnAllocation.original_payment_id)) == 'PAY-1'
    assert db.scalar(select(ReturnAllocation.refund_amount)) == Decimal('50.00')
