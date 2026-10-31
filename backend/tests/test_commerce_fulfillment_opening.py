"""Adopt real historical spent funds and media IDs, never issue stock twice."""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from app.commerce_migration import order_service, finance_service, fulfillment_service as service
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.commerce_migration.finance_schemas import FinanceOpeningManifest
from app.commerce_migration.fulfillment_schemas import FulfillmentOpeningManifest
from app.finance.models import FinanceEvent
from app.finance import service as finance_commands
from app.finance.schemas import FinanceAction
from app.inventory.models import StockLedger, StockReservation
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, Receivable, ShipmentSettlement, SettlementItem, SettlementApplication, ShipmentOutbound
from app.models.commission import SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus
from app.receipt.models import Receipt
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto
from app.shipping_inspection import outbound_service, service as inspection_service
from app.shipping_inspection.print_customer_service import with_customer_order_info
from app.shipping_inspection.print_service import with_owner_chinese_name
from tests.test_commerce_order_opening import inputs as order_inputs, seed_original_order
from tests.test_invoice_commerce import buyer
from tests.test_finance_local import finance
from tests.test_inventory_local import stock

DAY = date(2026, 10, 3)


def inputs(db, stock, finance, *, reservations=None, tag='OLD', tenant='tenant-A', existing_order=False,
           raw_order=None, shipment_items=None):
    customer, user, bank = finance
    if raw_order is None:
        raw_order = order_inputs(db, (customer, user), tag=tag, tenant=tenant)
    if reservations is not None:
        raw_order['orders'][0]['items'][0]['reservations'] = reservations
    original_cash = original_receipt = None
    existing_identity = raw_order['orders'][0].get('existing_invoice_id')
    if existing_order or existing_identity is not None:
        original = db.get(Invoice, existing_identity) if existing_identity else seed_original_order(db, raw_order, user)[0]
        from app.commerce_transition.service import policy
        if policy(db).phase == 'transition':
            # Seed the actual source ledger before freezing its closure; the
            # opening must reuse these IDs and one canonical bank principal.
            original_cash = ReceiptBatch(batch_no=f'{tag}-CASH', customer_id=f'{tag}-CUSTOMER', currency='USD',
                gross_amount=600, bank_account_id=bank.id, bank_reference=f'{tag}-CASH-BANK', collection_date=DAY,
                payment_type='bank_transfer', transaction_mode='legacy', request_key=f'{tag}-old-cash',
                request_hash='a'*64, created_by=int(user['sub']))
            db.add(original_cash); db.flush()
            original_receipt = Receipt(receipt_no=f'{tag}-old-receipt', invoice_id=original.id, batch_id=original_cash.id,
                customer_id=f'{tag}-CUSTOMER', source='manual', purpose='ordinary', amount=600, bank_charge=0,
                currency='USD', collection_date=DAY, payment_type='bank_transfer', collect_status=1, sync_status='synced',
                xiaoman_order_id=f'{tag}-ORDER', xiaoman_receipt_id=f'{tag}-PAYMENT', request_key=f'{tag}-old-receipt',
                request_hash='b'*64, created_by=int(user['sub']))
            db.add(original_receipt); db.flush()
            from tests.test_commerce_finance_opening import account_domain
            from app.finance.transition_identity import reconcile_legacy_identity
            domain = account_domain(db, bank)
            reconcile_legacy_identity(db, domain_id=domain.id, transaction_id=original_cash.bank_reference,
                batch_id=original_cash.id, statement_reference='Original whole-order bank statement', actor_id=int(user['sub']))
    order_body = OrderOpeningManifest.model_validate(raw_order)
    order = order_service.apply_manifest(db, order_body, user)['orders'][0]
    invoice = db.get(Invoice, order['invoice_id'])
    target = db.get(Receivable, order['receivables'][0]['receivable_id'])
    old_batch = CommissionBatch(batch_name='Source paid', period_start=DAY, period_end=DAY, status='confirmed')
    db.add(old_batch); db.flush()
    db.add_all([SyncedPayment(payment_id=f'{tag}-PAYMENT', order_id=f'{tag}-ORDER', customer_id=f'{tag}-CUSTOMER',
        payment_date=DAY, payment_amount=600, service_fee=0, exchange_rate=650, real_amount_rmb=3900),
        CommissionDetail(batch_id=old_batch.id, payment_id=f'{tag}-PAYMENT', order_id=f'{tag}-ORDER', customer_id=f'{tag}-CUSTOMER',
            payment_amount=600, salesperson_id='old-sales', salesperson_rate=Decimal('.02'), salesperson_commission=Decimal('7.01'), status='paid'),
        PaymentCommissionStatus(payment_id=f'{tag}-PAYMENT', batch_id=old_batch.id)])
    db.flush()
    body = FinanceOpeningManifest.model_validate(dict(batch_key='whole-cash' if tag == 'OLD' else f'whole-cash-{tag}', source='okki', tenant=tenant,
        cutover_date=DAY, evidence_sha256='c'*64, review_reference='Synthetic full paid source', payments=[dict(
            external_id=f'{tag}-CASH', batch_no=f'{tag}-CASH', local_customer_id=customer.id, source_customer_id=f'{tag}-CUSTOMER',
            customer_external_identity_id=order_body.orders[0].customer_external_identity_id,
            bank_account_id=bank.id, bank_reference=f'{tag}-CASH-BANK', currency='USD', gross_amount='600', actual_bank_fee='0',
            allocated_amount='600', refunded_amount='0', bank_charge_total='0', available_amount='0', rate_to_cny='6.5', rate_to_usd='1',
            collection_date=DAY, confirmed_date=DAY, confirmed_by=int(user['sub']), confirmed_at='2026-10-03T08:00:00',
            payment_type='bank_transfer', allocations=[dict(external_id=f'{tag}-ALLOCATION', invoice_id=invoice.id,
                receivable_id=target.id, order_binding_record_id=order['record_id'], original_receipt_id=f'{tag}-PAYMENT',
                source_customer_id=f'{tag}-CUSTOMER', purpose='ordinary', collection_date=DAY, amount='600', remaining_commission_usd='600')])]))
    if original_cash:
        payment = body.payments[0]
        body = body.model_copy(update={'payments': [payment.model_copy(update={'existing_batch_id': original_cash.id,
            'allocations': [payment.allocations[0].model_copy(update={'existing_receipt_id': original_receipt.id})]})]})
    cash = finance_service.apply_manifest(db, body, user)['payments'][0]
    raw = dict(batch_key='whole-fulfillment' if tag == 'OLD' else f'whole-fulfillment-{tag}', source='okki', tenant=tenant, cutover_date=DAY,
        evidence_sha256='d'*64, review_reference='Synthetic complete original fulfillment', orders=[dict(
            order_binding_record_id=order['record_id'], shipments=[dict(source_settlement_id=f'{tag}-SHIP', sequence=1,
                settlement_no='OLD-SHIP-NO', outbound_no='ORIGINAL-OUT', outbound_record_id='original-mirror-record',
                outbound_invoice_id='original-api-outbound', shipped_at='2026-10-03T12:00:00', business_date=DAY,
                warehouse_id=stock[1][0].id, is_final=False, goods_amount='600', packaging_amount='0', handling_amount='0',
                freight_amount='0', deposit_applied='0', deposit_charge_applied='0', goods_payment_due='600',
                goods_payment_charge='0', new_payment_due='600', inspection_id=None,
                items=shipment_items if shipment_items is not None else [dict(source_item_id=f'{tag}-ITEM',
                    outbound_item_id='original-media-item', quantity=6, line_amount='600')],
                applications=[dict(original_receipt_id=f'{tag}-PAYMENT', component='goods', amount='600', bank_charge='0',
                    released_amount='0', released_bank_charge='0')])])])
    return raw, invoice, cash, order, user


def counts(db):
    return [db.scalar(select(func.count()).select_from(model)) for model in
        (ShipmentSettlement, SettlementItem, SettlementApplication, ShipmentOutbound, StockLedger, FinanceEvent, SyncedPayment)]


def test_historical_dispatch_consumes_cash_preserves_full_order_and_issues_no_stock(db, stock, finance):
    raw, invoice, cash, order, user = inputs(db, stock, finance)
    body = FulfillmentOpeningManifest.model_validate(raw)
    before = counts(db)
    assert service.preview(db, body)['can_apply'] and counts(db) == before
    result = service.apply_manifest(db, body, user); db.commit()
    assert counts(db) == [1, 1, 1, 1, 0, 2, 1]
    assert invoice.total_amount == 1000 and invoice.items[0].quantity == 10 and invoice.items[0].stock_shipped_quantity == 6
    reservation = db.scalars(select(StockReservation)).one()
    assert reservation.shipped == 6 and reservation.reserved == 0
    app = db.scalars(select(SettlementApplication)).one()
    assert app.amount == app.effective_amount == 600 and app.status == 'applied'
    assert service.apply_manifest(db, body, user) == result
    assert service.apply_manifest(db, body.model_copy(update={'batch_key': 'history-repeat'}), user)['orders'] == result['orders']
    assert counts(db) == [1, 1, 1, 1, 0, 2, 1] and invoice.items[0].stock_shipped_quantity == 6
    # Release only the order readiness gate to test the ordinary reversal
    # consumer; the integrated activation test covers the real gate separately.
    invoice.commerce_status = 'partially_shipped'
    receipt = db.get(Receipt, cash['allocations'][0]['receipt_id'])
    with pytest.raises(ValueError, match='占用'):
        finance_commands.reverse_allocation(db, receipt.id, FinanceAction(request_key='reuse-shipped-cash', expected_version=receipt.version,
            business_date=DAY, amount=1, reason='Cannot reuse historical consumed funds'), user)


def test_original_inspection_media_and_barcodes_read_locally_with_no_mirror_queries(db, stock, finance, monkeypatch):
    raw, invoice, cash, order, user = inputs(db, stock, finance)
    inspection = ShippingInspection(outbound_record_id='original-mirror-record', outbound_no='ORIGINAL-OUT',
        customer_name='Original buyer', status='submitted', submitted_at=datetime(2026, 10, 3, 11), submitted_by=int(user['sub']), photo_count=1)
    db.add(inspection); db.flush()
    photo = ShippingInspectionPhoto(inspection_id=inspection.id, item_id='original-media-item', file_path='original.jpg', media_type='image')
    video = ShippingInspectionPhoto(inspection_id=inspection.id, item_id=None, file_path='original.mp4', media_type='video')
    db.add_all([photo, video]); db.flush()
    raw['orders'][0]['shipments'][0]['inspection_id'] = inspection.id
    old_media = [(p.id, p.item_id, p.file_path, p.created_at) for p in [photo, video]]
    result = service.apply_manifest(db, FulfillmentOpeningManifest.model_validate(raw), user); db.commit()
    outbound_id = result['orders'][0]['shipments'][0]['outbound_id']
    assert inspection.local_outbound_id == outbound_id and inspection.outbound_record_id == 'original-mirror-record'
    assert [(p.id, p.item_id, p.file_path, p.created_at) for p in [photo, video]] == old_media
    monkeypatch.setattr(outbound_service, '_record_columns', lambda *_: pytest.fail('Historical native read queried mirror'))
    from app.invoice import okki_client
    monkeypatch.setattr(okki_client, 'get_outbound_info', lambda *_: pytest.fail('Historical native print called remote transaction API'))
    for identity in ['original-mirror-record', 'original-api-outbound', f'local-{outbound_id}']:
        header = outbound_service.get_outbound_record(db, identity)
        assert header['outbound_record_id'] == 'original-mirror-record' and header['transaction_mode'] == 'local'
        assert header['outbound_invoice_id'] == 'original-api-outbound' and header['company_id'] == f'ark:{finance[0].id}'
        assert outbound_service.list_outbound_items(db, identity)[0]['item_id'] == 'original-media-item'
        assert with_customer_order_info(db, header)['order_amount_text'] == 'USD 1,000.00'
        assert with_owner_chinese_name(db, header)['owner_name'] == header['owner_name']
        assert inspection_service._get_by_outbound_id(db, identity).id == inspection.id
    detail = inspection_service.get_record_detail(db, inspection.id)
    assert detail['photos'][0]['id'] == photo.id and detail['photos'][0]['item_id'] == 'original-media-item'
    assert detail['videos'][0]['id'] == video.id
    from app.shipping_inspection.local_outbound_service import ensure_editable
    with pytest.raises(ValueError, match='完成'):
        ensure_editable(db, 'original-mirror-record')
    with pytest.raises(ValueError, match='完成'):
        inspection_service.recall(db, inspection.id, int(user['sub']), inspection.edit_version)
    assert inspection.status == 'submitted' and [(p.id, p.item_id, p.file_path, p.created_at) for p in [photo, video]] == old_media


@pytest.mark.parametrize('change', ['omitted_shipment', 'quantity', 'receipt', 'fee', 'date', 'inspection_omitted'])
def test_historical_fulfillment_proofs_reject_mismatches_before_mutation(db, stock, finance, change):
    raw, invoice, cash, order, user = inputs(db, stock, finance)
    ship = raw['orders'][0]['shipments'][0]
    if change == 'omitted_shipment':
        ship['source_settlement_id'] = 'OTHER-SHIP'
    elif change == 'quantity':
        ship['items'][0]['quantity'] = 5
    elif change == 'receipt':
        ship['applications'][0]['original_receipt_id'] = 'OTHER-PAYMENT'
    elif change == 'fee':
        ship.update(handling_amount='1', goods_payment_due='601', goods_payment_charge='1', new_payment_due='601')
        ship['applications'][0].update(amount='601', bank_charge='1')
    elif change == 'date':
        ship.update(shipped_at='2026-09-30T12:00:00', business_date=date(2026, 9, 30))
    else:
        db.add(ShippingInspection(outbound_record_id=ship['outbound_record_id'], outbound_no=ship['outbound_no'], status='submitted'))
        db.flush()
    body = FulfillmentOpeningManifest.model_validate(raw)
    before = counts(db)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError):
        service.apply_manifest(db, body, user)
    db.commit()
    assert counts(db) == before and invoice.items[0].stock_shipped_quantity == 0


def test_missing_spent_allocation_is_rejected_by_manifest_not_reusable_as_new_cash(db, stock, finance):
    raw, _, _, _, _ = inputs(db, stock, finance)
    raw['orders'][0]['shipments'][0]['applications'] = []
    with pytest.raises(ValidationError, match='消费'):
        FulfillmentOpeningManifest.model_validate(raw)


def test_late_historical_dispatch_failure_is_savepoint_atomic(db, stock, finance, monkeypatch):
    raw, invoice, _, _, user = inputs(db, stock, finance)
    before = counts(db)
    original = service._post
    def fail(*args):
        original(*args)
        raise ValueError('Synthetic late historical dispatch failure')
    monkeypatch.setattr(service, '_post', fail)
    with pytest.raises(ValueError, match='late'):
        service.apply_manifest(db, FulfillmentOpeningManifest.model_validate(raw), user)
    db.commit()
    assert counts(db) == before and invoice.items[0].stock_shipped_quantity == 0


@pytest.mark.parametrize('incoming', ['outbound_record_id', 'outbound_invoice_id'])
@pytest.mark.parametrize('existing', ['original_outbound_record_id', 'original_outbound_invoice_id'])
def test_cross_field_historical_alias_conflict_does_not_break_original_barcode(db, stock, finance, incoming, existing):
    raw, invoice, _, _, user = inputs(db, stock, finance)
    # A distinct already-adopted outbound owns either kind of original alias.
    settlement = ShipmentSettlement(invoice_id=invoice.id, settlement_no='UNRELATED', sequence=99, state='shipped',
        is_final=0, quote={}, quote_hash='a'*64, request_key='unrelated-alias', request_hash='a'*64, created_by=int(user['sub']))
    db.add(settlement); db.flush()
    outbound = ShipmentOutbound(settlement_id=settlement.id, invoice_id=invoice.id, outbound_no='UNRELATED',
        remote_id='unrelated-remote', status='local_shipped', payload_hash='a'*64,
        payload={'transaction_mode': 'local', existing: 'occupied-alias'})
    db.add(outbound); db.flush()
    # _check first validates complete ownership of existing settlements, so
    # place the unrelated owner on a different invoice without hiding it.
    other = Invoice(invoice_no='OTHER-ALIAS', customer_id='OTHER', customer_name='Other', invoice_date=DAY,
        currency='USD', created_by=int(user['sub']))
    db.add(other); db.flush(); settlement.invoice_id = outbound.invoice_id = other.id
    raw['orders'][0]['shipments'][0][incoming] = 'occupied-alias'
    body = FulfillmentOpeningManifest.model_validate(raw)
    result = service.preview(db, body)
    assert not result['can_apply'] and '出库身份' in result['conflicts'][0]['message']
    with pytest.raises(ValueError, match='出库身份'):
        service.apply_manifest(db, body, user)
    db.commit()
    from app.shipping_inspection.local_outbound_service import get
    assert get(db, 'occupied-alias').id == outbound.id
    assert invoice.items[0].stock_shipped_quantity == 0


def test_manifest_checks_api_alias_namespace_and_cross_field_collisions(db, stock, finance):
    raw, _, _, _, _ = inputs(db, stock, finance)
    raw['orders'][0]['shipments'][0]['outbound_invoice_id'] = 'local-123'
    with pytest.raises(ValidationError, match='命名空间'):
        FulfillmentOpeningManifest.model_validate(raw)
    raw['orders'][0]['shipments'][0]['outbound_invoice_id'] = 'second-record'
    second = deepcopy(raw['orders'][0]['shipments'][0])
    second.update(source_settlement_id='SECOND', sequence=2, settlement_no='SECOND', outbound_no='SECOND',
        outbound_record_id='second-record', outbound_invoice_id='second-api')
    raw['orders'][0]['shipments'].append(second)
    with pytest.raises(ValidationError, match='交叉重复'):
        FulfillmentOpeningManifest.model_validate(raw)


def test_historical_spent_funds_cannot_be_freed_without_real_original_reversal(db, stock, finance):
    raw, invoice, _, _, user = inputs(db, stock, finance)
    raw['orders'][0]['shipments'][0]['applications'][0]['released_amount'] = '600'
    body = FulfillmentOpeningManifest.model_validate(raw)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='冲回依据'):
        service.apply_manifest(db, body, user)
    db.commit()
    assert invoice.items[0].stock_shipped_quantity == 0


def test_cancelled_original_settlement_is_preserved_beside_adopted_shipment(db, stock, finance):
    raw, _, _, _, user = inputs(db, stock, finance)
    old = ShipmentSettlement(invoice_id=db.scalars(select(Invoice)).one().id, settlement_no='CANCELLED-OLD', sequence=7,
        state='cancelled', is_final=0, quote={'original': 'cancelled'}, quote_hash='f'*64, request_key='old-cancelled',
        request_hash='f'*64, created_by=int(user['sub']))
    db.add(old); db.flush()
    identity, created_at = old.id, old.created_at
    assert service.preview(db, FulfillmentOpeningManifest.model_validate(raw))['can_apply']
    service.apply_manifest(db, FulfillmentOpeningManifest.model_validate(raw), user); db.commit()
    assert old.id == identity and old.created_at == created_at and old.state == 'cancelled' and old.quote == {'original': 'cancelled'}
