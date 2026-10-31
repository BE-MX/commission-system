"""Partial historical deposits and separate batch freight survive later shipments."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.commerce_migration import order_service, finance_service, fulfillment_service, inventory_service, activation_service
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.commerce_migration.finance_schemas import FinanceOpeningManifest
from app.commerce_migration.fulfillment_schemas import FulfillmentOpeningManifest
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.commerce_migration.activation_schemas import ActivationManifest, ActivationSelection
from app.finance import service as finance_commands
from app.finance.schemas import AllocationCreate
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, Receivable, ShipmentSettlement, SettlementApplication
from app.inventory.models import StockBalance, StockLedger
from app.models.commission import SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus
from app.receipt.models import Receipt
from tests.test_commerce_order_opening import inputs as order_inputs, seed_original_order
from tests.test_finance_local import finance, payment, cmd
from tests.test_local_fulfillment import create_batch, act, inspect
from tests.test_inventory_local import stock
from tests.test_invoice_commerce import buyer

DAY = date(2026, 10, 3)


def verify_presale_continuity(db, stock, finance, *, tag='PS', tenant='tenant-PS'):
    customer, user, bank = finance
    raw_order = order_inputs(db, (customer, user), tag=tag, tenant=tenant, catalog_code=tag)
    source = raw_order['orders'][0]
    source.update(order_type='presale', local_deposit_amount='300', source_received_amount='824', source_balance_amount='200',
        historical_shipment_ids=[f'{tag}-SHIP-A', f'{tag}-SHIP-B'])
    source['items'][0]['reservations'] = [dict(warehouse_id=stock[1][0].id, quantity=4)]
    source['receivables'][0]['paid_amount'] = '800'
    for suffix, amount in [('A', '11'), ('B', '13')]:
        source['receivables'].append(dict(external_id=f'{tag}-FREIGHT-{suffix}', kind='freight',
            source_settlement_id=f'{tag}-SHIP-{suffix}', amount=amount, handling_amount='0', paid_amount=amount,
            due_date=DAY, adjustments=[]))
    from app.commerce_transition.service import policy
    old_cash, old_receipts = None, {}
    if policy(db).phase == 'transition':
        original, _ = seed_original_order(db, raw_order, user)
        old_cash = ReceiptBatch(batch_no=f'{tag}-CASH', customer_id=f'{tag}-CUSTOMER', currency='USD', gross_amount=824,
            transaction_mode='legacy', bank_account_id=bank.id, bank_reference=f'{tag}-original-bank', collection_date=DAY,
            payment_type='bank_transfer', request_key=f'{tag}-old-cash', request_hash='a'*64, created_by=int(user['sub']))
        db.add(old_cash); db.flush()
        for suffix, amount, purpose in [('GOODS', 500, 'presale_balance'), ('DEPOSIT', 300, 'presale_deposit'),
                                       ('F-A', 11, 'freight'), ('F-B', 13, 'freight')]:
            receipt = Receipt(receipt_no=f'{tag}-old-{suffix}', invoice_id=original.id, batch_id=old_cash.id,
                customer_id=f'{tag}-CUSTOMER', source='manual', purpose=purpose, amount=amount, bank_charge=0,
                currency='USD', collection_date=DAY, payment_type='bank_transfer', collect_status=1, sync_status='synced',
                xiaoman_order_id=f'{tag}-ORDER', xiaoman_receipt_id=f'{tag}-PAY-{suffix}',
                request_key=f'{tag}-old-{suffix}', request_hash='b'*64, created_by=int(user['sub']))
            db.add(receipt); db.flush(); old_receipts[receipt.xiaoman_receipt_id] = receipt.id
        from tests.test_commerce_finance_opening import account_domain
        from app.finance.transition_identity import reconcile_legacy_identity
        domain = account_domain(db, bank)
        reconcile_legacy_identity(db, domain_id=domain.id, transaction_id=old_cash.bank_reference,
            batch_id=old_cash.id, statement_reference='Original presale principal and allocations', actor_id=int(user['sub']))
    order = order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw_order), user)['orders'][0]
    invoice = db.get(Invoice, order['invoice_id'])
    targets = {row['external_id']: row['receivable_id'] for row in order['receivables']}
    paid = CommissionBatch(batch_name=f'{tag}-original-paid', period_start=DAY, period_end=DAY, status='confirmed')
    db.add(paid); db.flush()
    allocations = []
    for suffix, amount, purpose, target in [
        ('GOODS', '500', 'presale_balance', f'{tag}-AR'), ('DEPOSIT', '300', 'presale_deposit', f'{tag}-AR'),
        ('F-A', '11', 'freight', f'{tag}-FREIGHT-A'), ('F-B', '13', 'freight', f'{tag}-FREIGHT-B')]:
        identity = f'{tag}-PAY-{suffix}'
        if purpose != 'freight':
            db.add_all([SyncedPayment(payment_id=identity, order_id=f'{tag}-ORDER', customer_id=f'{tag}-CUSTOMER',
                payment_date=DAY, payment_amount=amount, service_fee=0, exchange_rate=650,
                real_amount_rmb=Decimal(amount)*Decimal('6.5')),
                CommissionDetail(batch_id=paid.id, payment_id=identity, order_id=f'{tag}-ORDER', customer_id=f'{tag}-CUSTOMER',
                    payment_amount=amount, salesperson_id='original-sales', salesperson_rate=Decimal('.02'),
                    salesperson_commission=Decimal(amount)*Decimal('.02'), status='paid'),
                PaymentCommissionStatus(payment_id=identity, batch_id=paid.id)])
        allocations.append(dict(external_id=f'{tag}-ALLOC-{suffix}', invoice_id=invoice.id, receivable_id=targets[target],
            order_binding_record_id=order['record_id'], original_receipt_id=identity, source_customer_id=f'{tag}-CUSTOMER',
            purpose=purpose, collection_date=DAY, amount=amount, remaining_commission_usd=amount if purpose != 'freight' else '0'))
    db.flush()
    cash = FinanceOpeningManifest.model_validate(dict(batch_key=f'{tag}-cash', source='okki', tenant=tenant, cutover_date=DAY,
        evidence_sha256='c'*64, review_reference='Synthetic partial deposit and two freight sources', payments=[dict(
            external_id=f'{tag}-CASH', batch_no=f'{tag}-CASH', local_customer_id=customer.id, source_customer_id=f'{tag}-CUSTOMER',
            customer_external_identity_id=source['customer_external_identity_id'], bank_account_id=bank.id,
            bank_reference=f'{tag}-original-bank', currency='USD', gross_amount='824', actual_bank_fee='0',
            allocated_amount='824', refunded_amount='0', bank_charge_total='0', available_amount='0', rate_to_cny='6.5', rate_to_usd='1',
            collection_date=DAY, confirmed_date=DAY, confirmed_by=int(user['sub']), confirmed_at='2026-10-03T08:00:00',
            payment_type='bank_transfer', allocations=allocations)]))
    if old_cash is not None:
        payment_row = cash.payments[0]
        cash = cash.model_copy(update={'payments': [payment_row.model_copy(update={'existing_batch_id': old_cash.id,
            'allocations': [a.model_copy(update={'existing_receipt_id': old_receipts[a.original_receipt_id]})
                            for a in payment_row.allocations]})]})
    finance_service.apply_manifest(db, cash, user)
    shipments = []
    for index, suffix, quantity, amount, due, deposit, freight in [
        (1, 'A', 2, '200', '100', '100', '11'), (2, 'B', 4, '400', '400', '0', '13')]:
        applications = [dict(original_receipt_id=f'{tag}-PAY-GOODS', component='goods', amount=due,
            bank_charge='0', released_amount='0', released_bank_charge='0'),
            dict(original_receipt_id=f'{tag}-PAY-F-{suffix}', component='freight', amount=freight,
                bank_charge='0', released_amount='0', released_bank_charge='0')]
        if deposit != '0':
            applications.append(dict(original_receipt_id=f'{tag}-PAY-DEPOSIT', component='deposit', amount=deposit,
                bank_charge='0', released_amount='0', released_bank_charge='0'))
        shipments.append(dict(source_settlement_id=f'{tag}-SHIP-{suffix}', sequence=index,
            settlement_no=f'{tag}-OLD-SHIP-{suffix}', outbound_no=f'{tag}-OLD-OUT-{suffix}',
            outbound_record_id=f'{tag}-old-record-{suffix}', outbound_invoice_id=f'{tag}-old-api-{suffix}',
            shipped_at='2026-10-03T12:00:00', business_date=DAY, warehouse_id=stock[1][0].id, is_final=False,
            goods_amount=amount, packaging_amount='0', handling_amount='0', freight_amount=freight,
            deposit_applied=deposit, deposit_charge_applied='0', goods_payment_due=due, goods_payment_charge='0',
            new_payment_due=str(Decimal(due)+Decimal(freight)), inspection_id=None,
            items=[dict(source_item_id=f'{tag}-ITEM', outbound_item_id=f'{tag}-old-item-{suffix}', quantity=quantity, line_amount=amount)],
            applications=applications))
    historical = FulfillmentOpeningManifest.model_validate(dict(batch_key=f'{tag}-fulfillment', source='okki', tenant=tenant,
        cutover_date=DAY, evidence_sha256='d'*64, review_reference='Synthetic historical partial deposit consumption',
        orders=[dict(order_binding_record_id=order['record_id'], shipments=shipments)]))
    wrong = deepcopy(historical.model_dump(mode='json'))
    for ship, swapped in zip(wrong['orders'][0]['shipments'], ['B', 'A'], strict=True):
        next(app for app in ship['applications'] if app['component'] == 'freight')['original_receipt_id'] = f'{tag}-PAY-F-{swapped}'
    bad = FulfillmentOpeningManifest.model_validate(wrong)
    assert any('不属于' in conflict['message'] for conflict in fulfillment_service.preview(db, bad)['conflicts'])
    with pytest.raises(ValueError, match='不属于'):
        fulfillment_service.apply_manifest(db, bad, user)
    assert db.scalar(select(func.count()).select_from(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice.id)) == 0
    result = fulfillment_service.apply_manifest(db, historical, user)
    assert db.scalar(select(func.count()).select_from(StockLedger).where(StockLedger.sku_id == invoice.items[0].local_sku_id)) == 0
    inventory_service.apply_manifest(db, InventoryOpeningManifest(batch_key=f'{tag}-physical', source='physical', tenant='warehouse',
        cutover_date=DAY, evidence_sha256='f'*64, review_reference='Synthetic presale physical closing', stocks=[dict(
            external_id=f'{tag}-bucket', mode='initialize', warehouse_id=stock[1][0].id, local_sku_id=invoice.items[0].local_sku_id,
            quality='sellable', on_hand=10, reserved=0)], materials=[]), user)
    prepared = activation_service.prepare(db, ActivationSelection(request_key=f'{tag}-enable', record_ids=[order['record_id']]))
    assert prepared['report']['can_activate'], prepared['report']
    activation_service.activate(db, ActivationManifest.model_validate(prepared['command']), user)
    db.commit()
    payment_batch = finance_commands.register(db, payment(customer, bank, request_key=f'{tag}-future-cash',
        bank_reference=f'{tag}-future-bank', gross_amount='217', actual_bank_fee=0, collection_date=DAY), user)
    finance_commands.confirm(db, payment_batch.id, cmd(f'{tag}-future-confirm', payment_batch.version).model_copy(update={'business_date': DAY}), user)
    for suffix, quantity, freight, due, deposit in [('C', 1, '5', '100.00', '0.00'), ('D', 3, '12', '100.00', '200.00')]:
        row = create_batch(db, invoice, user, stock[1][0], quantity, f'{tag}-future-{suffix}', freight=freight)
        assert row.quote['goods_payment_due'] == due and row.quote['deposit_applied'] == deposit
        finance_commands.allocate(db, payment_batch.id, AllocationCreate(request_key=f'{tag}-future-goods-{suffix}',
            expected_version=payment_batch.version, invoice_id=invoice.id, receivable_id=targets[f'{tag}-AR'],
            settlement_id=row.id, amount=due, purpose='ordinary', business_date=DAY), user)
        freight_target = db.scalar(select(Receivable).where(Receivable.settlement_id == row.id, Receivable.kind == 'freight'))
        finance_commands.allocate(db, payment_batch.id, AllocationCreate(request_key=f'{tag}-future-freight-{suffix}',
            expected_version=payment_batch.version, invoice_id=invoice.id, receivable_id=freight_target.id,
            settlement_id=row.id, amount=freight, purpose='ordinary', business_date=DAY), user)
        act(db, row, user, f'{tag}-ready-{suffix}', 'ready')
        checked = inspect(db, row, user)
        act(db, row, user, f'{tag}-ship-{suffix}', 'ship', inspection_version=checked.edit_version)
        db.commit()
    apps = db.scalars(select(SettlementApplication).join(ShipmentSettlement,
        ShipmentSettlement.id == SettlementApplication.settlement_id).where(ShipmentSettlement.invoice_id == invoice.id)).all()
    assert sum(app.effective_amount for app in apps if app.component == 'deposit') == 300
    assert sum(app.effective_amount for app in apps if app.component == 'freight') == 41
    assert invoice.total_amount == 1000 and invoice.internal_received == 1041 and invoice.internal_balance == 0
    assert invoice.items[0].stock_shipped_quantity == 10
    bucket = db.scalar(select(StockBalance).where(StockBalance.sku_id == invoice.items[0].local_sku_id,
        StockBalance.warehouse_id == stock[1][0].id, StockBalance.quality == 'sellable'))
    assert bucket.on_hand == 6 and bucket.reserved == 0
    assert fulfillment_service.apply_manifest(db, historical, user) == result
    assert sum(row.effective_amount for row in db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id))) == 1041
    return dict(original_deposit=300, historical_deposit_consumed=100, final_deposit_consumed=200,
        original_freight=[11, 13], future_freight=[5, 12], cross_batch_freight_rejected=True,
        full_contract=1000, total_received=1041, remaining_balance=0, physical_stock=6)


def test_historical_partial_deposit_and_two_batch_freight_continue_exactly(db, stock, finance):
    verify_presale_continuity(db, stock, finance)
